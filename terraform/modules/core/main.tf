# modules/core resources created by the module. Does not mutate existing customer-owned
# resources. Deploys the offline generation plane; the edge serving/routing plane is
# added when serving_mode = "edge" (the default).

locals {
  prefix          = var.name_prefix
  vertex_location = var.vertex_location != "" ? var.vertex_location : "global"
  sitemap_url     = var.sitemap_url != "" ? var.sitemap_url : "${var.site_base_url}/sitemap.xml"
  content_bucket  = var.gcs_bucket_name != "" ? var.gcs_bucket_name : "${var.project_id}-${var.name_prefix}-content"
  labels          = merge({ app = "ai-content-optimizer" }, var.labels)
}

