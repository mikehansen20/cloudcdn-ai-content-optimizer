# Offline Cascade Worker (`services/worker`)

Core generation processing pipeline deployed as a Cloud Run service subscribed to the Pub/Sub crawl topic (`<name_prefix>-crawl`).

## Processing Cascade

For each incoming URL message, the worker executes a multi-stage deterministic processing cascade:

```
Conditional Fetch (ETag / Last-Modified)
       │
       ▼
DOM Extraction & Traversal (Heuristic Harvest)
       │
       ▼
Completeness & Quality Evaluation Gate
       ├─────────────────────────────────┐
       │ (Passes Quality Threshold)      │ (Escalated: Complex Layout / SPA)
       ▼                                 ▼
Deterministic Markdown           Vertex AI Gemini Grounded Extraction
       │                                 │
       └────────────────┬────────────────┘
                        ▼
         Schema Validation & Front-Matter
                        │
                        ▼
      Write Optimized Markdown (.md) to Cloud Storage
```

## Running Locally for Testing

To run the offline cascade pipeline against a local site or HTML fixture:

```bash
cd services/worker
PYTHONPATH=src:../common/src .venv/bin/python -m cascade.cli --url https://example.com/page
```
