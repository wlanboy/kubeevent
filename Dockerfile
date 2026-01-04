FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY db.py .
COPY models.py .
COPY metrics.py .
COPY k8s_watcher.py .
COPY runtime.py .
COPY routes.py .
COPY main.py .
COPY static/ ./static/
COPY templates/ ./templates/

RUN mkdir -p /app/data

EXPOSE 5000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]