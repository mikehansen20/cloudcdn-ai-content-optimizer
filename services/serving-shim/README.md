# Serving Shim Origin Proxy (`services/serving-shim`)

Lightweight FastAPI Cloud Run service deployed as the backend origin for AI-crawler traffic (`/_ai_optimized/*`).

## Serving Behavior

1. **Pre-Generated Content Hit (GCS)**:
   - When an AI crawler requests a page that exists in the Cloud Storage bucket (`.md`), the service immediately streams the pre-generated Markdown with edge-cacheable HTTP headers (`Cache-Control: public, max-age=3600`).
2. **Root AI Index Discovery**:
   - Requests to `/llms.txt` and `/llms-full.txt` are served directly as `text/plain` site indexes.
3. **Cache Miss & Self-Healing (Origin Proxy + Enqueue)**:
   - If pre-generated Markdown is not yet present in storage (`GCS 404`), the service:
     1. Proxies live origin HTML back to the crawler immediately (`Cache-Control: no-store`) so the crawler never encounters a broken link.
     2. Asynchronously enqueues the URL to the Pub/Sub crawl topic (`<name_prefix>-crawl`), triggering an immediate background generation task so subsequent crawler visits receive optimized Markdown.
