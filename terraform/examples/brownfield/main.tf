# Brownfield example for deploying AI Content Optimizer into an existing GCP project
# that serves a site through a global external Application Load Balancer. (Cloud
# CDN is enabled by the module on its optimized-content backend, not a prerequisite.)
#
# "Brownfield" deployment means an existing project, site, and load balancer are present.
# Deploys the solution: crawls the site on a schedule, writes optimized Markdown
# and llms.txt to a GCS bucket, and sets up backend and edge detection resources to
# route AI crawlers at the load balancer.
#
# The module never modifies existing load balancers. It creates its own resources and
# prints two commands (see outputs) to apply to your URL map and forwarding rule.
#
# Copy this directory as the starting point for your own root config, fill in
# terraform.tfvars (see terraform.tfvars.example), and set `source` below to where you
# keep modules/core (a local path, a git ref, or a module registry).

provider "google" {
  project = var.project_id
  region  = var.region
}

module "aico" {
  source = "../../modules/core"

  project_id    = var.project_id
  region        = var.region
  site_base_url = var.site_base_url

  # Where to find your sitemap. Leave empty to use {site_base_url}/sitemap.xml.
  sitemap_url = var.sitemap_url

  # Optimize only your public content; skip account/cart/checkout paths.
  include_paths = var.include_paths
  exclude_paths = var.exclude_paths

  # Heading for the generated llms.txt.
  site_title = var.site_title

  # Model & Vertex location settings
  gemini_model    = var.gemini_model
  vertex_location = var.vertex_location

  # Your EXISTING load balancer. These are optional, but providing them lets the module
  # render fully copy-paste-ready commands in the manual_step_1 / manual_step_2 outputs.
  # The module never modifies either resource.
  existing_url_map                 = var.existing_url_map
  existing_forwarding_rule         = var.existing_forwarding_rule
  existing_default_backend_service = var.existing_default_backend_service

  # Optional advanced performance & scaling knobs
  name_prefix             = var.name_prefix
  cdn_default_ttl_seconds = var.cdn_default_ttl_seconds
  client_ttl              = var.client_ttl
  enable_cdn_logging      = var.enable_cdn_logging
  cdn_log_sample_rate     = var.cdn_log_sample_rate
  worker_min_instances    = var.worker_min_instances
  worker_max_instances    = var.worker_max_instances
  worker_concurrency      = var.worker_concurrency
}

# --- Generation plane ---

output "content_bucket" {
  description = "GCS bucket holding the generated Markdown + llms.txt."
  value       = module.aico.content_bucket
}

output "trigger_crawl_command" {
  description = "Trigger initial crawl with interactive live progress bar, real-time page count, and automatic llms.txt manifest rebuild:"
  value       = "../../../scripts/trigger-crawl.sh --project=${var.project_id} --region=${var.region} --bucket=${module.aico.content_bucket} --topic=${module.aico.crawl_topic_name} --enumerator-job=${module.aico.enumerator_job_name} --llms-job=${module.aico.llms_job_name} --sitemap-url=\"${var.sitemap_url != "" ? var.sitemap_url : (var.site_base_url != "" ? "${trimsuffix(var.site_base_url, "/")}/sitemap.xml" : "")}\""
}

output "tail_logs_command" {
  description = "Tail live execution logs in your terminal."
  value       = module.aico.tail_logs_command
}

output "build_job_name" {
  description = "Generate/refresh content: gcloud run jobs execute <this> --region <region> --wait."
  value       = module.aico.build_job_name
}

output "llms_job_name" {
  description = "Job that rebuilds llms.txt / llms-full.txt."
  value       = module.aico.llms_job_name
}

output "region" {
  description = "Primary GCP region for Cloud Run jobs."
  value       = module.aico.region
}

output "crawler_user_agent" {
  description = "Allowlist this User-Agent in your WAF/CDN so the crawl isn't blocked."
  value       = module.aico.crawler_user_agent
}

# --- Edge routing (apply these two to your load balancer; see the Integration Guide) ---

output "manual_step_1_urlmap" {
  description = "Copy-paste command: add the optimized-content path rule to YOUR url map."
  value       = module.aico.manual_step_1_urlmap
}

output "manual_step_2_edge_extension" {
  description = "Copy-paste command: attach the AI-crawler detector to YOUR forwarding rule."
  value       = module.aico.manual_step_2_edge_extension
}

output "verification_curl" {
  description = "Ready-made check: an AI-crawler request vs a browser request against your site."
  value       = module.aico.verification_curl
}

output "serving_endpoint_url" {
  description = "Direct URL of the serving backend (test it before wiring the load balancer)."
  value       = module.aico.serving_endpoint_url
}
