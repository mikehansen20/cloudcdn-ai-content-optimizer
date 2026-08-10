# Module interface OUTPUTS.

output "content_bucket" {
  value       = google_storage_bucket.content.name
  description = "GCS bucket holding generated content (primary deliverable in content_only mode)."
}

output "vertex_location" {
  value       = local.vertex_location
  description = "Resolved Vertex region (== data-residency region)."
}

output "region" {
  value       = var.region
  description = "Primary Google Cloud region where Cloud Run services and jobs reside."
}

output "serving_mode" {
  value       = var.serving_mode
  description = "Active serving mode."
}

output "worker_service_url" {
  value       = google_cloud_run_v2_service.worker.uri
  description = "Worker Cloud Run URL (the Pub/Sub push target)."
}

output "renderer_service_url" {
  value       = google_cloud_run_v2_service.renderer.uri
  description = "Renderer Cloud Run URL (internal worker access only)."
}

output "enumerator_job_name" {
  value       = google_cloud_run_v2_job.enumerator.name
  description = "Cloud Run job that fans the sitemap into crawl messages."
}

# Interface name: the job a customer triggers to kick off a manual rebuild
# (`gcloud run jobs execute <build_job_name>`). In content_only mode that is the enumerator,
# which fans the sitemap into per-URL crawl messages.
output "build_job_name" {
  value       = google_cloud_run_v2_job.enumerator.name
  description = "Cloud Run job to trigger a manual content rebuild."
}

output "llms_job_name" {
  value       = google_cloud_run_v2_job.llms.name
  description = "Cloud Run job that rebuilds llms.txt / llms-full.txt."
}

output "crawler_user_agent" {
  value       = var.crawler_user_agent
  description = "User-Agent the crawler sends. Allowlist this in your WAF/CDN so the crawl is not blocked."
}

output "crawl_topic_name" {
  value       = google_pubsub_topic.crawl.name
  description = "Pub/Sub topic for crawl messages."
}

# --- edge-plane outputs; null unless serving_mode = "edge" ---

output "ai_path_prefix" {
  value       = var.ai_path_prefix
  description = "Path prefix the URL-map rule must match (routes AI crawlers to the optimized backend)."
}

output "optimized_backend_service" {
  value       = one(google_compute_backend_service.optimized[*].name)
  description = "Backend service to reference in your URL-map path rule (manual step 1)."
}

output "wasm_plugin_resource" {
  value       = one(google_network_services_wasm_plugin.edge[*].id)
  description = "Full resource path of the WasmPlugin the edge extension attaches (manual step 2)."
}

output "serving_endpoint_url" {
  value       = one(google_cloud_run_v2_service.shim[*].uri)
  description = "Direct serving-shim URL. Test optimized content before wiring the load balancer."
}

output "manual_step_1_urlmap" {
  description = "MANUAL STEP 1: run this command against your URL map (additive; the module never modifies it). Routes the AI path plus /llms.txt and /llms-full.txt to the optimized backend service. NOTE: --path-rules expects ONLY the short backend service name, NOT a full URL path."
  value       = var.serving_mode != "edge" ? null : <<-EOT
gcloud compute url-maps add-path-matcher ${var.existing_url_map != "" ? var.existing_url_map : "<YOUR_URL_MAP>"} \
  --path-matcher-name=ai-optimizer \
  --new-hosts="${local.site_host}" \
  --default-service=${var.existing_default_backend_service != "" ? var.existing_default_backend_service : "<YOUR_EXISTING_DEFAULT_BACKEND_SERVICE>"} \
      --path-rules="${var.ai_path_prefix}/*=${one(google_compute_backend_service.optimized[*].name)},/llms.txt=${one(google_compute_backend_service.optimized[*].name)},/llms-full.txt=${one(google_compute_backend_service.optimized[*].name)}" \
      --global --project=${var.project_id}
  EOT
}

output "manual_step_2_edge_extension" {
  description = "MANUAL STEP 2: attach the detection plugin to your forwarding rule. NOTE: a forwarding rule allows only ONE edge extension; if you already use one, merge into that chain."
  value       = var.serving_mode != "edge" ? null : <<-EOT
cat <<'YAML' > aico-edge-extension.yaml
name: ${var.name_prefix}-edge-ext
forwardingRules:
- https://www.googleapis.com/compute/v1/projects/${var.project_id}/global/forwardingRules/${var.existing_forwarding_rule != "" ? var.existing_forwarding_rule : "<YOUR_FORWARDING_RULE>"}
loadBalancingScheme: EXTERNAL_MANAGED
extensionChains:
- name: chain1
  matchCondition:
    celExpression: "true"
  extensions:
  - name: ${var.name_prefix}-edge
    service: ${one(google_network_services_wasm_plugin.edge[*].id)}
    supportedEvents:
    - REQUEST_HEADERS
YAML
gcloud service-extensions lb-edge-extensions import ${var.name_prefix}-edge-ext \
  --source=aico-edge-extension.yaml --location=global --project=${var.project_id}
  EOT
}

output "trigger_crawl_command" {
  description = "Trigger initial crawl with interactive live progress bar, real-time page count, and automatic llms.txt manifest rebuild:"
  value       = "./scripts/trigger-crawl.sh --project=${var.project_id} --region=${var.region} --bucket=${google_storage_bucket.content.name} --topic=${google_pubsub_topic.crawl.name} --enumerator-job=${google_cloud_run_v2_job.enumerator.name} --llms-job=${google_cloud_run_v2_job.llms.name} --sitemap-url=\"${local.sitemap_url}\""
}

output "tail_logs_command" {
  description = "Optional copy-paste gcloud command to stream live crawl execution logs in your terminal:"
  value       = "gcloud logging tail 'resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"${google_cloud_run_v2_job.enumerator.name}\"' --project=${var.project_id}"
}

output "verification_curl" {
  description = "Prove the bot-vs-human split once the two manual steps are applied."
  value       = var.serving_mode != "edge" ? null : <<-EOT
    # AI crawler → optimized markdown (the edge plugin rewrites the path):
    curl -sS -H 'User-Agent: Mozilla/5.0 (compatible; GPTBot/1.1; +https://openai.com/gptbot)' https://${local.site_host}/<A_REAL_PATH>
    # Human browser → your normal page, untouched:
    curl -sS -H 'User-Agent: Mozilla/5.0' https://${local.site_host}/<A_REAL_PATH>
    # llms.txt served to ANY client at the site root (no special UA needed):
    curl -sS https://${local.site_host}/llms.txt
  EOT
}
