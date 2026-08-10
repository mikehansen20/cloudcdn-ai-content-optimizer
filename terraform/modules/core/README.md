# Terraform Core Module (`terraform/modules/core`)

Self-contained Terraform module that deploys the entire AI Content Optimizer offline generation plane, serving origin proxy, edge detection extension, and dedicated IAM permissions.

## Architecture & Resource Ownership

- **Creates & Manages Its Own Resources**:
  - Regional Cloud Storage bucket (`<name_prefix>-content-...`) for Markdown and `llms.txt` storage.
  - Pub/Sub topics (`<name_prefix>-crawl` and `<name_prefix>-dlq`) with dead-letter queue handling.
  - Dedicated Cloud Run services (`worker`, `renderer`, `serving-shim`).
  - Cloud Run execution jobs (`build` and `llms`) with scheduled Cloud Scheduler triggers.
  - Cloud CDN backend service (`Serverless NEG` pointing to `serving-shim`).
  - Service Extensions `WasmPlugin` for edge AI-crawler detection.
  - Dedicated per-service service accounts with least-privilege IAM roles.
- **Never Modifies Existing Infrastructure**:
  - Does **not** modify your existing Application Load Balancer, URL map, backend services, DNS records, or TLS certificates.
  - Outputs exact copy-paste `gcloud` commands (`manual_step_1_urlmap`, `manual_step_2_edge_extension`) so operators retain explicit control over load balancer routing.

## Usage

See [`terraform/examples/brownfield`](../../examples/brownfield) for a ready-to-copy integration example and variable reference.
