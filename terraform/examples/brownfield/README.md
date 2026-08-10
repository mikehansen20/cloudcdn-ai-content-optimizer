# Brownfield example

Deploy the AI Content Optimizer into an existing GCP project that already serves a site through a
global external Application Load Balancer. It crawls your site on a schedule, writes optimized,
LLM-ingestible Markdown + `llms.txt` to a GCS bucket, and stands up the backend + edge detector that
route AI crawlers to that content at your load balancer. (Cloud CDN is enabled by the module on the
optimized-content backend it creates; you don't need it on your existing load balancer.)

The module **never** touches your load balancer, URL map, backends, DNS, or certs. It creates its own
resources and prints two copy-paste commands (`manual_step_1_urlmap`, `manual_step_2_edge_extension`)
that **you** apply to your load balancer and can undo at any time.

## Use it

```bash
cp terraform.tfvars.example terraform.tfvars   # then edit it
terraform init
terraform apply
```

Set `source` in `main.tf` to where you keep `modules/core` (a local path, a git ref, or a module
registry). In this repo it points at `../../modules/core` so the example validates as-is.

## What you get (outputs)

| Output | Use |
|---|---|
| `content_bucket` | The GCS bucket with generated Markdown + `llms.txt`. |
| `build_job_name` | Generate/refresh content: `gcloud run jobs execute <name> --region <region> --wait`. |
| `llms_job_name` | Job that rebuilds `llms.txt` / `llms-full.txt`. |
| `crawler_user_agent` | Allowlist this in your WAF/CDN so the crawl isn't blocked. |
| `manual_step_1_urlmap` | Copy-paste command to route AI crawlers in your URL map. |
| `manual_step_2_edge_extension` | Copy-paste command to attach the AI-crawler detector at the edge. |
| `verification_curl` | Ready-made AI-crawler-vs-browser check against your site. |
| `serving_endpoint_url` | Direct URL of the serving backend (test before wiring the load balancer). |

## Full walkthrough

See the [Integration Guide](../../../docs/INTEGRATION_GUIDE.md) for prerequisites, the exact order of
operations, verification, and rollback.
