import os
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

@pytest.fixture
def mock_s3():
    with patch("main.s3_client") as mock:
        yield mock

@pytest.fixture
def mock_subprocess():
    with patch("main.subprocess.run") as mock:
        yield mock

@pytest.fixture
def mock_requests():
    with patch("main.requests.get") as mock:
        yield mock

def test_convert_endpoint_success(mock_s3, mock_subprocess, mock_requests):
    # Mock requests response
    mock_response = MagicMock()
    mock_response.iter_content.return_value = [b"fake content"]
    mock_requests.return_value = mock_response

    # Mock subprocess (LibreOffice)
    mock_subprocess.return_value.stdout = b"Success"
    
    # Mock S3 upload and presign
    mock_s3.generate_presigned_url.return_value = "https://s3.amazonaws.com/bucket/converted.pdf?signature"

    # Mock file existence for output check
    with patch("os.path.exists", side_effect=lambda p: True): 
        with patch("os.remove") as mock_remove:
            # We need to mock open as well to avoid writing to /tmp in test if possible, 
            # but the code writes to /tmp. Let's just let it write or mock open.
            # For simplicity, we'll let it try to write to /tmp/uuid... which is safe enough, 
            # or better, mock open.
            with patch("builtins.open", new_callable=MagicMock):
                 response = client.post("/convert", json={"input_url": "https://example.com/test.docx"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "job_id" in data
    assert data["download_url"] == "https://s3.amazonaws.com/bucket/converted.pdf?signature"
    
    # Verify S3 upload called
    mock_s3.upload_file.assert_called_once()

def test_convert_endpoint_subprocess_error(mock_s3, mock_subprocess, mock_requests):
    # Mock requests
    mock_requests.return_value.iter_content.return_value = [b"data"]
    
    # Mock subprocess failure
    mock_subprocess.side_effect = Exception("LibreOffice failed")

    with patch("builtins.open", new_callable=MagicMock):
        with patch("os.remove"):
            response = client.post("/convert", json={"input_url": "http://example.com/bad.docx"})
    
    assert response.status_code == 500
    assert "LibreOffice failed" in response.json()["detail"]

