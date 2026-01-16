FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y curl iputils-ping && rm -rf /var/lib/apt/lists/*
# Cài thư viện cần thiết
COPY requirements.txt .
RUN apt-get update && apt-get install -y gcc libffi-dev build-essential && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt
RUN pip install matplotlib reportlab

# Copy source code
COPY gate_app.py .
EXPOSE 8000
# Chạy bằng uvicorn để khởi động FastAPI
CMD ["uvicorn", "gate_app:app", "--host", "0.0.0.0", "--port", "8000"]
