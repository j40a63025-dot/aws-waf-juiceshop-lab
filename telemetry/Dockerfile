FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY app.py .
USER 10001:10001
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--no-access-log"]
