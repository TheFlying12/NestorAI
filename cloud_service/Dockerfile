FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY cloud_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["sh", "-c", "alembic -c cloud_service/alembic.ini upgrade head && uvicorn cloud_service.app.main:app --host 0.0.0.0 --port 8080"]
