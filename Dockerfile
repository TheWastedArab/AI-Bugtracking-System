FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY backend backend
COPY migrations migrations
COPY alembic.ini .
RUN useradd --create-home triage && mkdir -p /app/artifacts /app/.mail-preview && chown -R triage:triage /app
USER triage
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
