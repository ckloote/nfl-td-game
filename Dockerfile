# One image, one process, one origin: FastAPI serves the API and the built React app.
# The SQLite database lives on a volume mounted at /data (see README, "Deploying").

FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STATIC_DIR=/app/frontend/dist \
    DATABASE_URL=sqlite:////data/app.db \
    COOKIE_SECURE=true
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app
COPY --from=frontend /frontend/dist /app/frontend/dist

# Exactly one worker: the refresh job and SQLite both assume a single process.
# The platform's proxy terminates TLS, so trust its X-Forwarded-* headers.
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips '*'"]
