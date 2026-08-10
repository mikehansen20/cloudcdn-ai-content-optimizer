# Shared Services Common (`aico_common`)

Shared Python library modules imported by `services/worker` and `services/serving-shim`.

## Modules

- **`ssrf.py`**: Server-Side Request Forgery (SSRF) and security validation guard. Ensures all origin fetches strictly target the configured `site_base_url` host and blocks private, link-local, or cloud metadata IP ranges (`169.254.169.254`, RFC 1918, RFC 4193).
- **`fetch.py`**: Standardized HTTP fetch client with automated retry handling, redirect validation, and SSRF guard integration.
- **`storage.py` / `gcs_storage.py`**: Cloud Storage abstraction layer for writing and reading optimized Markdown (`.md`) content and standard site indexes (`llms.txt`, `llms-full.txt`).
- **`pubsub.py`**: Resilient asynchronous Pub/Sub publisher with structured logging and guaranteed message flush on service termination.
