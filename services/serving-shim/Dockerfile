# Serving shim routing and proxy service at CDN origin for AI crawler paths.
# Uses aico_common modules (fetch, ssrf, storage, pubsub).
# Build from the services/ directory (needs common/ as a sibling):
#   docker build -f serving-shim/Dockerfile -t aico-serving-shim services/
FROM python:3.13-slim

WORKDIR /app

COPY serving-shim/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY common/src/aico_common/ /app/aico_common/
COPY serving-shim/app.py /app/

ENV PYTHONPATH=/app
EXPOSE 8080
# Cloud Run injects $PORT (default 8080). Auth-required backend in prod (URL-map target).
CMD ["sh", "-c", "python -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
