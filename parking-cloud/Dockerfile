FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    libffi-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir python-multipart
RUN pip install pytz
RUN pip install qrcode[pil] pillow

COPY gates_api.py .

EXPOSE 8010

CMD ["uvicorn", "gates_api:app", "--host", "0.0.0.0", "--port", "8010"]
