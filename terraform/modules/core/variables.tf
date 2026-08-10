# Module interface INPUTS. Generation-plane inputs first, then edge-plane inputs.

variable "project_id" {
  type        = string
  description = "Customer GCP project; all module resources are created here."
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Region for Cloud Run, Pub/Sub, GCS, jobs."
}

variable "name_prefix" {
  type        = string
  default     = "ai-optimizer"
  description = "Prefix namespacing every created resource."
}

variable "site_base_url" {
  type        = string
  description = "Public base URL of the customer's site (the offline crawler fetches from here)."
}

variable "sitemap_url" {
  type        = string
  default     = ""
  description = "Sitemap to enumerate. Empty defaults to <site_base_url>/sitemap.xml."
}

variable "include_paths" {
  type        = list(string)
  default     = ["/*"]
  description = "URL path globs to optimize."
}

variable "exclude_paths" {
  type        = list(string)
  default     = []
  description = "Globs to skip (e.g. /account/*, /cart/*)."
}

variable "gemini_model" {
  type        = string
  default     = "gemini-3.5-flash"
  description = "Vertex model for offline extraction (verify current id at deploy)."
}

variable "vertex_location" {
  type        = string
  default     = "global"
  description = "Vertex location for model API calls. Defaults to 'global' for Gemini 3.5 Flash."
}

variable "rebuild_schedule" {
  type        = string
  default     = "0 */6 * * *"
  description = "Cron for the periodic crawl (enumerator) job."
}

variable "llms_schedule" {
  type        = string
  default     = "30 */6 * * *"
  description = "Cron for the llms.txt rebuild job; offset after rebuild_schedule so pages land first."
}

variable "site_title" {
  type        = string
  default     = "Site"
  description = "Heading used at the top of the generated llms.txt."
}

variable "crawler_user_agent" {
  type        = string
  default     = "AIContentOptimizer/1.0 (GCP Cloud CDN content optimizer)"
  description = "Distinctive, allowlistable User-Agent the crawler sends. Allowlist this in your WAF/CDN (see docs/INTEGRATION_GUIDE.md); customize to add your own identifier if you like."
}

variable "content_cache_ttl" {
  type        = number
  default     = 3600
  description = "Cache-Control/CDN TTL (seconds) for served optimized content."
}

variable "pending_marker_ttl" {
  type        = number
  default     = 3600
  description = "TTL (seconds) of the atomic pending/<path> dedup marker (lifecycle rule)."
}

variable "gcs_bucket_name" {
  type        = string
  default     = ""
  description = "Content bucket name; empty => module names it."
}

variable "serving_mode" {
  type    = string
  default = "edge"
  # edge (default): generate optimized content AND route AI crawlers to it at your load
  # balancer via a Service Extension and Cloud CDN.
  # content_only: undocumented escape hatch that deploys only the offline generation plane
  # (no LB routing); you serve the content bucket yourself. Not covered by the docs.
  description = "edge (full solution: generate + route at the load balancer). content_only is an undocumented generate-only escape hatch."
  validation {
    condition     = contains(["content_only", "edge"], var.serving_mode)
    error_message = "serving_mode must be content_only or edge."
  }
}

# --- edge-plane inputs; used only when serving_mode = "edge" ---

variable "ai_path_prefix" {
  type        = string
  default     = "/_ai_optimized"
  description = "Path prefix the edge plugin rewrites AI-crawler requests to; the customer's URL-map rule routes <ai_path_prefix>/* to the optimized backend."
}

variable "ai_bot_user_agents" {
  type = list(string)
  default = [
    "gptbot", "chatgpt-user", "oai-searchbot", "chatgpt agent",
    "claudebot", "claude-user", "anthropic-ai",
    "perplexitybot", "perplexity-user",
    "google-extended", "gemini-deep-research", "google-notebooklm",
    "ccbot", "bytespider", "amazonbot", "amzn-user", "meta-externalagent",
    "duckassistbot", "kimi-user", "mistralai-user", "cohere-ai", "deepseekbot",
    "youbot", "iaskspider", "petalbot",
  ]
  description = "Lowercased User-Agent substrings routed to optimized content. Excludes search crawlers to avoid cloaking. Passed to the edge plugin as config."
}

variable "origin_404_behavior" {
  type        = string
  default     = "proxy_and_generate"
  description = "proxy_and_generate (shim self-heals a miss) | notfound (shim 404s on a miss)."
  validation {
    condition     = contains(["proxy_and_generate", "notfound"], var.origin_404_behavior)
    error_message = "origin_404_behavior must be proxy_and_generate or notfound."
  }
}

variable "edge_plugin_image" {
  type        = string
  default     = "us-central1-docker.pkg.dev/upperstack-tools/aico/aico-edge-plugin:v1"
  description = "Published OCI image containing the compiled edge-plugin wasm. Public, pull-only default; customers never build it."
}

variable "existing_url_map" {
  type        = string
  default     = ""
  description = "Name of existing URL map. Optional: used to render the manual_step_1 output. The module never modifies it."
}

variable "existing_forwarding_rule" {
  type        = string
  default     = ""
  description = "Name of existing global forwarding rule. Optional: used to render the manual_step_2 output. The module never modifies it."
}

variable "existing_default_backend_service" {
  type        = string
  default     = ""
  description = "Name of existing default backend service serving the origin site. Optional: used to populate --default-service in manual_step_1 output. The module never modifies it."
}

# Published, pull-only image refs. Customers deploy with these DEFAULTS and never build:
# the images live in a public Artifact Registry (allUsers has reader) so any project can
# pull them with no access grant. Override only if you mirror the images into your own
# registry.
variable "worker_image" {
  type        = string
  default     = "us-central1-docker.pkg.dev/upperstack-tools/aico/aico-worker:latest"
  description = "Published worker container image ref (customers pull; never build)."
}

variable "renderer_image" {
  type        = string
  default     = "us-central1-docker.pkg.dev/upperstack-tools/aico/aico-renderer:latest"
  description = "Published renderer container image ref."
}

variable "serving_shim_image" {
  type        = string
  default     = "us-central1-docker.pkg.dev/upperstack-tools/aico/aico-serving-shim:latest"
  description = "Published serving-shim container image ref (edge mode; customers pull, never build)."
}

variable "labels" {
  type        = map(string)
  default     = {}
  description = "Labels applied to all created resources."
}

variable "bucket_force_destroy" {
  type        = bool
  default     = false
  description = "Allow terraform destroy of the content bucket even if non-empty (dev only)."
}

# --- Advanced performance & scaling knobs ---

variable "worker_min_instances" {
  type        = number
  default     = 1
  description = "Minimum Cloud Run worker container instances (1 keeps a warm worker ready 24/7 for instant zero-latency processing; 0 for scale-to-zero)."
}

variable "worker_max_instances" {
  type        = number
  default     = 10
  description = "Max Cloud Run worker container instances (bounds Vertex AI API quota and protects origin server). For enterprise 50k+ catalog sites, set to 35."
}

variable "worker_concurrency" {
  type        = number
  default     = 16
  description = "Max concurrent Pub/Sub push requests per worker container instance. For enterprise 50k+ catalog sites, set to 80 for high-throughput async processing."
}

variable "cdn_default_ttl_seconds" {
  type        = number
  default     = 3600
  description = "Edge CDN cache TTL in seconds (default: 1 hour); also configures the serving-shim Cache-Control max-age."
}

variable "client_ttl" {
  type        = number
  default     = null
  description = "Optional client/browser cache TTL (seconds) for Cloud CDN cdn_policy."
}

variable "enable_cdn_logging" {
  type        = bool
  default     = true
  description = "Enable Cloud CDN request logging on the optimized backend service."
}

variable "cdn_log_sample_rate" {
  type        = number
  default     = 1.0
  description = "Sampling rate for Cloud CDN logs (0.0 to 1.0)."
}


