FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY listbot_v170.py .

CMD ["python", "listbot_v170.py"]
