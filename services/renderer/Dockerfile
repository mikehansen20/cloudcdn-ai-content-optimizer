# Renderer service hosting headless Chromium via Playwright.
# Build from the services/ directory (needs common/ as a sibling):
#   docker build -f renderer/Dockerfile -t aico-renderer services/
FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

WORKDIR /app

# Python dependencies (Chromium and system libraries are in the base image).
COPY renderer/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Shared SSRF guard via PYTHONPATH and service code.
COPY common/src/aico_common/ /app/aico_common/
COPY renderer/app.py renderer/browser.py /app/

ENV PYTHONPATH=/app
EXPOSE 8080
# Cloud Run injects $PORT (default 8080 locally). Not --allow-unauthenticated:
# this service is internal-only, called by the worker.
CMD ["sh", "-c", "python -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
