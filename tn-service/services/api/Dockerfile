FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY certs /app/certs
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host=0.0.0.0", "--port=8000", "--ssl-keyfile=/app/certs/key.pem", "--ssl-certfile=/app/certs/cert.pem"]
