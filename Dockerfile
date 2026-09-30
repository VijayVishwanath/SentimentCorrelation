# ---- build the React UI
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- runtime: one process serves API + built UI
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEX_ENVIRONMENT=production PORT=8080
WORKDIR /app
# libgomp: OpenMP runtime required by LightGBM (predictive model)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY data/DEX_Sentinel_Simulated_Dataset.xlsx data/
COPY --from=ui /ui/dist frontend/dist
RUN useradd -m dex && chown -R dex /app
USER dex
WORKDIR /app/backend
EXPOSE 8080
# Hypercorn speaks HTTP/2 cleartext (h2c): on Cloud Run with --use-http2 this lifts the 32 MiB HTTP/1
# request-size cap so Module 8 can accept 200 MB uploads. One worker: all state lives in this process.
CMD ["sh", "-c", "exec hypercorn app.main:app --bind 0.0.0.0:${PORT} --workers 1 --keep-alive 650 --access-logfile -"]
