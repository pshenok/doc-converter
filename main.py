import os
import subprocess
import uuid
import shutil
import boto3
import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from botocore.exceptions import NoCredentialsError

app = FastAPI()

# Configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)

class ConversionRequest(BaseModel):
    input_url: str

def cleanup_files(file_paths):
    for path in file_paths:
        if os.path.exists(path):
            os.remove(path)

@app.on_event("startup")
async def check_dependencies():
    """Verify that LibreOffice is installed and available."""
    if not shutil.which("soffice"):
        print("WARNING: 'soffice' (LibreOffice) not found in PATH. Conversion will fail.")

@app.post("/convert")
async def convert_doc_to_pdf(request: ConversionRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    input_filename = f"{job_id}_input"
    output_filename = f"{job_id}_input.pdf" # LibreOffice keeps original name + .pdf
    
    # Determine extension from URL or default to .docx if unknown
    # Simple heuristic, can be improved
    if ".doc" in request.input_url:
         ext = ".doc"
    else:
         ext = ".docx"
    
    local_input_path = f"/tmp/{input_filename}{ext}"
    local_output_dir = "/tmp"
    local_output_path = f"/tmp/{input_filename}.pdf" # Expected output path

    try:
        # 1. Download file
        response = requests.get(request.input_url, stream=True)
        response.raise_for_status()
        with open(local_input_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # 2. Convert using LibreOffice
        # soffice --headless --convert-to pdf --outdir /tmp /tmp/input.docx
        cmd = [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            local_output_dir,
            local_input_path
        ]
        
        # Add timeout to prevent hanging processes (e.g. 60 seconds)
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        
        if not os.path.exists(local_output_path):
             raise HTTPException(status_code=500, detail="Conversion failed, output file not found")

        # 3. Upload to S3
        s3_key = f"converted/{job_id}.pdf"
        s3_client.upload_file(local_output_path, S3_BUCKET_NAME, s3_key)

        # 4. Generate Presigned URL
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': s3_key},
            ExpiresIn=3600 # 1 hour
        )
        
        # Cleanup in background
        background_tasks.add_task(cleanup_files, [local_input_path, local_output_path])

        return {
            "status": "success",
            "job_id": job_id,
            "download_url": presigned_url
        }

    except subprocess.TimeoutExpired:
        cleanup_files([local_input_path])
        print("Error: LibreOffice conversion timed out")
        raise HTTPException(status_code=504, detail="Conversion timed out")
    except subprocess.CalledProcessError as e:
        cleanup_files([local_input_path])
        print(f"LibreOffice Error: {e.stderr.decode()}")
        raise HTTPException(status_code=500, detail="Document conversion failed")
    except Exception as e:
        cleanup_files([local_input_path, local_output_path])
        print(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
