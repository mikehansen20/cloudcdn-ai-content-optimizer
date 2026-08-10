# Worker service running the offline cascade. It calls the
# renderer service over HTTP (RemoteRenderer) using a standard Python base image.
# Build from the services/ directory (needs common/ as a sibling):
#   docker build -f worker/Dockerfile -t aico-worker services/
FROM python:3.13-slim

WORKDIR /app

COPY worker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# aico_common + the cascade package via PYTHONPATH (no py-version pin clash) + the app.
COPY common/src/aico_common/ /app/aico_common/
COPY worker/src/cascade/ /app/cascade/
COPY worker/app.py /app/

ENV PYTHONPATH=/app
EXPOSE 8080
# Cloud Run injects $PORT (default 8080). Pub/Sub-push OIDC-authenticated in prod.
CMD ["sh", "-c", "python -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
