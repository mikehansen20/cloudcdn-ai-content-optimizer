# Integration Guide

Deploy the AI Content Optimizer into your Google Cloud project to automatically generate clean Markdown content from your site and serve it to AI crawlers (GPTBot, Gemini, Perplexity, etc.) at Cloud CDN edge, while human visitors remain unaffected.

---

## ⚡ Quickstart (5 Steps)

### Prerequisites

**1. Authenticate with Google Cloud:**
```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

**2. Check existing load balancer resources:**
You need an existing global external Application Load Balancer. Note your resource names:
```bash
gcloud compute url-maps list
gcloud compute forwarding-rules list --global
gcloud compute backend-services list --global
```

**3. Check Cloud Run unauthenticated deployment permission:**
Confirm your project allows unauthenticated Cloud Run services (used behind the serverless NEG with load-balancer-only ingress):
```bash
gcloud run deploy arc-check --image=us-docker.pkg.dev/cloudrun/container/hello --allow-unauthenticated --region=us-central1 --quiet
# If successful, clean up check service:
gcloud run services delete arc-check --region=us-central1 --quiet
```
*(If this fails with an org policy error, ask your GCP org admin to allow unauthenticated Cloud Run for this project).*

**4. Check Edge Extensions limit:**
A forwarding rule allows **one** edge extension chain. If you already have one, check with:
```bash
gcloud service-extensions lb-edge-extensions list --location=global
```

---

### Step 1: Deploy Stack

Clone the repository and enter the brownfield example directory:
```bash
git clone https://github.com/mikehansen20/cloudcdn-ai-content-optimizer.git
cd cloudcdn-ai-content-optimizer/terraform/examples/brownfield
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:
```hcl
project_id                       = "YOUR_PROJECT_ID"
region                           = "us-central1"                # Primary GCP region for worker/GCS
site_base_url                    = "https://www.your-site.com"  # Base site URL
existing_url_map                 = "YOUR_URL_MAP"               # Populates manual output commands
existing_forwarding_rule         = "YOUR_FORWARDING_RULE"
existing_default_backend_service = "YOUR_DEFAULT_BACKEND_SERVICE"

# Optional path filters:
include_paths                    = ["/*"]
exclude_paths                    = ["/account/*", "/cart/*", "/checkout/*"]
site_title                       = "Your Site Name"
```

Apply Terraform:
```bash
terraform init
terraform apply
```
*(Note: If `apply` fails with a `409 Already Exists` on the content bucket, set `name_prefix = "my-site-optimizer"` in `terraform.tfvars` to customize the resource namespace).*

---

### Step 2: Allowlist Crawler User-Agent (Optional)

*Skip this step if you do not use a WAF or bot-mitigation provider (Cloud Armor, Cloudflare, Akamai).*

Retrieve the crawler's User-Agent string:
```bash
terraform output -raw crawler_user_agent
# Output: AIContentOptimizer/1.0 (GCP Cloud CDN content optimizer)
```
Add an allow rule for this User-Agent in your WAF or bot mitigation provider so sitemap and page fetches are not blocked with `403` challenges.

> **Note on Egress IPs:** Cloud Run egresses from dynamic Google IPs by default. If your WAF requires static IP allowlisting, attach Cloud NAT with a reserved static IP to the worker service.

---

### Step 3: Run Initial Crawl & Build `llms.txt`

Trigger the initial crawl and manifest build:
```bash
$(terraform output -raw trigger_crawl_command)
```
*(Optional: Stream live Cloud Run execution logs in a separate tab with `$(terraform output -raw tail_logs_command)`).*

Verify generated content in Cloud Storage:
```bash
gcloud storage ls "gs://$(terraform output -raw content_bucket)/"
```

#### 💡 Sites Without a Sitemap
The crawler is sitemap-driven (`{site_base_url}/sitemap.xml`). If your site lacks a sitemap:
1. **Generate a sitemap** via your CMS and host it at `{site_base_url}/sitemap.xml` (or set `sitemap_url` in `terraform.tfvars`).
2. **Or manually enqueue URLs via Pub/Sub**:
   ```bash
   gcloud pubsub topics publish ai-optimizer-crawl --message='{"url":"https://www.your-site.com/"}'
   gcloud pubsub topics publish ai-optimizer-crawl --message='{"url":"https://www.your-site.com/about"}'
   ```

---

### Step 4: Route AI Crawlers at Load Balancer

Choose the option below matching your URL map configuration. You can either **inspect & copy/paste** the commands or execute them directly via **one-liner execution**.

<details open>
<summary><b>Option A: If your host has NO existing path matcher</b></summary>

<br>

**Method 1: Inspect & Copy/Paste (Recommended)**
```bash
# Print rendered URL map command to copy/paste:
terraform output manual_step_1_urlmap

# Print rendered Edge Extension YAML to copy/paste:
terraform output manual_step_2_edge_extension
```

**Method 2: One-Liner Execution**
```bash
# Pipe commands directly to bash:
terraform output -raw manual_step_1_urlmap | bash
terraform output -raw manual_step_2_edge_extension | bash
```

</details>

<details>
<summary><b>Option B: If your URL Map ALREADY has a path matcher (Most Common)</b></summary>

<br>

If your URL map already routes traffic for your host, adding a second path matcher causes a GCP conflict error. Export your URL map, add the 3 path rules to your existing `pathMatcher`, and re-import:

1. **Export URL map to YAML:**
   ```bash
   gcloud compute url-maps export YOUR_URL_MAP --destination=urlmap.yaml
   ```

2. **Add path rules to your existing `pathMatcher`:**
   ```yaml
   pathMatchers:
   - name: my-existing-path-matcher
     defaultService: projects/YOUR_PROJECT_ID/global/backendServices/your-origin-backend-service
     pathRules:
     # --- ADD THESE 3 PATH RULES FOR AI OPTIMIZER ---
     - paths:
       - /_ai_optimized/*
       - /llms.txt
       - /llms-full.txt
       service: projects/YOUR_PROJECT_ID/global/backendServices/ai-optimizer-optimized-backend
     # --- YOUR EXISTING PATH RULES REMAIN BELOW ---
     - paths:
       - /*
       service: projects/YOUR_PROJECT_ID/global/backendServices/your-origin-backend-service
   ```

3. **Import updated URL map:**
   ```bash
   gcloud compute url-maps import YOUR_URL_MAP --source=urlmap.yaml
   ```

4. **Attach Edge Extension:**
   ```bash
   # Inspect first:
   terraform output manual_step_2_edge_extension

   # Or execute directly:
   terraform output -raw manual_step_2_edge_extension | bash
   ```

> **Note on Service Names:** Load balancer `--path-rules` flags require ONLY the short **backend service name** (e.g. `ai-optimizer-optimized-backend`), NOT a full GCS URI or resource path.

</details>

---

### Step 5: Verify Deployment

Wait **~3–6 minutes** for CDN edge propagation, then execute verification:

```bash
terraform output -raw verification_curl
```
*(This tests the URL twice: once with an AI crawler User-Agent returning Markdown `text/markdown`, and once with a browser User-Agent returning HTML).*

Directly test the serving-shim endpoint:
```bash
curl -sSL "$(terraform output -raw serving_endpoint_url)/"
```

---

## 📘 Reference & Deep-Dives

* [Architecture & System Components](#architecture--system-components)
* [Dead-Letter Queue (DLQ) & Troubleshooting](#dead-letter-queue-dlq--troubleshooting)
* [Rollback & Teardown Protocol](#rollback--teardown-protocol)
* [Permissions & Security Matrix](#permissions--security-matrix)
* [Glossary of Terms](#glossary-of-terms)

---

### Architecture & System Components

Everything is created inside your project under a configurable `name_prefix` (default `ai-optimizer`).

| Component | What it is and does |
|---|---|
| **Content Bucket** (Cloud Storage) | Holds generated Markdown + `llms.txt`/`llms-full.txt`. |
| **Enumerator** (Cloud Run job) | Reads sitemap and publishes per-URL messages to Pub/Sub. |
| **Crawl Topic + DLQ** (Pub/Sub) | Carries per-URL work to worker; failed retries land in DLQ. |
| **Worker** (Cloud Run service) | Fetches pages, extracts content, and writes Markdown. Calls Gemini 3.5 Flash via Vertex AI only when needed. |
| **Renderer** (Cloud Run service) | Internal-only headless Chromium for client-side JS rendering. |
| **llms Builder** (Cloud Run job) | Compiles `llms.txt` / `llms-full.txt` from bucket objects. |
| **Cloud Scheduler** (2 jobs) | Triggers enumerator (every 6h) and llms builder on schedules. |
| **Serving-Shim** (Cloud Run service) | Serves pre-generated content to AI crawlers; self-heals missing pages on CDN miss. |
| **Optimized Backend + Serverless NEG** (Cloud CDN) | CDN backend fronting serving-shim. |
| **Edge Detector** (WasmPlugin) | Service Extension inspecting User-Agents at load balancer edge. |

#### Generation Flow (Offline, Scheduled):
1. `Cloud Scheduler` triggers `Enumerator` job.
2. `Enumerator` reads sitemap and publishes URLs to `Crawl Pub/Sub Topic`.
3. `Worker` receives push messages, fetches page (calling `Renderer` if JS-heavy), extracts content (calling `Vertex AI` Gemini if needed), and writes Markdown to `Content Bucket`.
4. `llms Builder` job runs on schedule to rebuild `llms.txt` / `llms-full.txt`.

#### Serving Flow (Request-Time Edge):
1. User request hits `Load Balancer`.
2. `WasmPlugin Edge Detector` inspects `User-Agent`:
   - **Humans & Search Engines (Googlebot/Bingbot)**: Pass straight to origin untouched.
   - **AI Crawlers (GPTBot, Gemini, Perplexity)**: Rewrites path to `/_ai_optimized/*` backend.
3. `Cloud CDN` / `Serving-Shim` returns pre-generated Markdown from `Content Bucket`.
4. On miss: `Serving-Shim` proxies origin HTML immediately (`no-store`) and enqueues URL for generation.

---

### Dead-Letter Queue (DLQ) & Troubleshooting

If a page fails after 5 retries (e.g. 404 in sitemap or WAF block), Pub/Sub moves it to `<name_prefix>-deadletter-sub` (default `ai-optimizer-deadletter-sub`).

Inspect failed messages:
```bash
gcloud pubsub subscriptions pull ai-optimizer-deadletter-sub --project YOUR_PROJECT_ID --limit 10 --auto-ack
```

Inspect worker execution logs:
```bash
gcloud logging read 'resource.labels.service_name="ai-optimizer-worker"' --project YOUR_PROJECT_ID --limit 20 --freshness=1h
```

---

### Rollback & Teardown Protocol

> [!IMPORTANT]
> **Teardown Order:** Step 4 attaches your load balancer to the module's WasmPlugin and BackendService. You **must remove manual load balancer bindings BEFORE running `terraform destroy`**, or GCP will block teardown with a `resource in use` error.

1. **Remove Edge Extension:**
   ```bash
   gcloud service-extensions lb-edge-extensions delete ai-optimizer-edge-ext --location=global --project=YOUR_PROJECT_ID
   ```
2. **Remove Path Matcher:**
   ```bash
   gcloud compute url-maps remove-path-matcher YOUR_URL_MAP --path-matcher-name=ai-optimizer --global --project=YOUR_PROJECT_ID
   ```
3. **Teardown Terraform Stack:**
   ```bash
   terraform destroy
   ```
   *(Content bucket is retained by default unless `bucket_force_destroy = true` is set).*

---

### Permissions & Security Matrix

Every component runs under its own dedicated service account using least-privilege principles. Predefined GCP roles are assigned by default to ensure clean deployment across all GCP organizations:

| Service Account | Predefined Role | Access & Scope |
|---|---|---|
| **Worker** | `roles/aiplatform.user`<br>`roles/storage.objectUser` | Vertex AI Gemini predictions & GCS content bucket read/create/overwrite. |
| **llms Builder** | `roles/storage.objectUser` | Content bucket metadata & body object read/write. |
| **Enumerator** | Pub/Sub Topic Publisher | Publish messages to crawl topic only. |
| **Scheduler** | `roles/run.invoker` | Trigger Cloud Run enumerator & llms jobs. |
| **PubSub Invoker** | `roles/run.invoker` | OIDC push execution of worker service. |
| **Renderer** | *None* | Internal-only invocation (URL in, DOM out). No GCP resource access. |

#### Granular Custom IAM Roles (Optional Strict Mode)
If your organization restricts predefined roles or requires custom IAM roles, you can substitute the following granular permissions in your own IAM policies:

* **Vertex AI Prediction Custom Role**:
  Replace `roles/aiplatform.user` on the worker service account with a custom role containing only:
  * `aiplatform.endpoints.predict`
* **GCS Content Bucket Custom Role**:
  Replace `roles/storage.objectUser` on worker and llms builder service accounts with a custom role containing only:
  * `storage.objects.get`
  * `storage.objects.create`
  * `storage.objects.delete`
  * `storage.objects.list`

---

### Glossary of Terms

| Term | Definition |
|---|---|
| **AI Crawler** | Automated bot fetching web pages for LLM assistants (e.g. GPTBot, PerplexityBot). Identified by User-Agent. |
| **Application Load Balancer** | Google Cloud HTTP(S) load balancer serving your site. |
| **URL Map** | Load balancer routing table mapping paths to backend services. |
| **Forwarding Rule** | Public IP and port entry point for the load balancer. |
| **Service Extension (Edge Extension)** | WasmPlugin running at load balancer edge to inspect headers and rewrite AI paths. |
| **Cloud CDN** | Content Delivery Network fronting the serving-shim to cache Markdown responses. |
| **`llms.txt`** | Standard Markdown site index served at site root (`/llms.txt`). |
| **ADC** | Application Default Credentials (`gcloud auth application-default login`). |
