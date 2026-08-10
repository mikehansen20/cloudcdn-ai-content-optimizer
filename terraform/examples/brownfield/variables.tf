# Inputs for the brownfield example. Only project_id + site_base_url are required;
# the rest have sensible defaults (mirroring modules/core).

variable "project_id" {
  type        = string
  description = "Your existing GCP project. All resources are created here."
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Region for Cloud Run, Pub/Sub, GCS, and the jobs (== data-residency region)."
}

variable "site_base_url" {
  type        = string
  description = "Public base URL of your site. The offline crawler fetches from here."
}

variable "sitemap_url" {
  type        = string
  default     = ""
  description = "Full URL of your sitemap. Leave empty to use {site_base_url}/sitemap.xml. The crawler is sitemap-driven and does not follow links, so every page to optimize must be listed there."
}

variable "include_paths" {
  type        = list(string)
  default     = ["/*"]
  description = "URL path globs to optimize."
}

variable "exclude_paths" {
  type        = list(string)
  default     = []
  description = "Globs to skip (e.g. /account/*, /cart/*, /checkout/*)."
}

variable "site_title" {
  type        = string
  default     = "Site"
  description = "Heading used at the top of the generated llms.txt."
}

variable "gemini_model" {
  type        = string
  default     = "gemini-3.5-flash"
  description = "Vertex model for offline extraction."
}

variable "name_prefix" {
  type        = string
  default     = "ai-optimizer"
  description = "Resource name prefix for all created GCP resources."
}

variable "vertex_location" {
  type        = string
  default     = "global"
  description = "Vertex region/location for model API calls. Defaults to 'global' for Gemini 3.5 Flash."
}

variable "existing_url_map" {
  type        = string
  default     = ""
  description = "Name of existing load balancer URL map. Optional: used to render the manual_step_1 command. The module never modifies it."
}

variable "existing_forwarding_rule" {
  type        = string
  default     = ""
  description = "Name of existing global forwarding rule. Optional: used to render the manual_step_2 command. The module never modifies it."
}

variable "existing_default_backend_service" {
  type        = string
  default     = ""
  description = "Name of existing default backend service serving the site. Optional: used to populate --default-service in manual_step_1 command. The module never modifies it."
}

# --- Optional advanced performance & scaling knobs ---

variable "cdn_default_ttl_seconds" {
  type        = number
  default     = 3600
  description = "Edge CDN cache TTL in seconds (default: 1 hour)."
}

variable "client_ttl" {
  type        = number
  default     = null
  description = "Optional client/browser cache TTL in seconds for Cloud CDN cdn_policy."
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

variable "worker_min_instances" {
  type        = number
  default     = 1
  description = "Minimum Cloud Run worker container instances (1 keeps a warm worker ready 24/7 for instant zero-latency processing; 0 for scale-to-zero)."
}

variable "worker_max_instances" {
  type        = number
  default     = 10
  description = "Max Cloud Run worker container instances (bounds Vertex AI API quota)."
}

variable "worker_concurrency" {
  type        = number
  default     = 16
  description = "Max concurrent Pub/Sub push requests per worker container instance."
}

# Container images default to published pull-only images.
