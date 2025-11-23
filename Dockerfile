FROM python:3.9-slim

# Install LibreOffice and Java (required for some LO operations)
RUN apt-get update && apt-get install -y \
    libreoffice \
    default-jre \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
