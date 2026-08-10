# Edge serving and routing plane. Created when serving_mode = "edge".
# The module creates dedicated backend and plugin resources without mutating existing
# load balancers, URL maps, or forwarding rules.

locals {
  edge_count = var.serving_mode == "edge" ? 1 : 0
  # APIs the edge plane needs on top of the offline set (apis.tf); enabled only in edge mode.
  edge_apis = var.serving_mode == "edge" ? toset(["compute.googleapis.com", "networkservices.googleapis.com"]) : toset([])
}

resource "google_project_service" "edge_apis" {
  for_each           = local.edge_apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# --- serving-shim: service account + least-privilege IAM ---
resource "google_service_account" "shim" {
  count        = local.edge_count
  account_id   = "${var.name_prefix}-shim"
  project      = var.project_id
  display_name = "AI Content Optimizer serving-shim"
}

resource "google_storage_bucket_iam_member" "shim_bucket" {
  count  = local.edge_count
  bucket = google_storage_bucket.content.name
  role   = "roles/storage.objectUser" # read objects + create the pending/<path> marker
  member = "serviceAccount:${google_service_account.shim[0].email}"
}

resource "google_pubsub_topic_iam_member" "shim_publishes_crawl" {
  count  = local.edge_count
  topic  = google_pubsub_topic.crawl.id
  role   = "roles/pubsub.publisher" # fire-and-forget enqueue on a miss
  member = "serviceAccount:${google_service_account.shim[0].email}"
}

# The external ALB reaches the shim through a serverless NEG, which requires the service to
# allow unauthenticated invocation. The shim only accepts LB ingress (below), so this exposes
# it via the load balancer only, not the public run.app URL. (Orgs that block allUsers on
# Cloud Run cannot use serverless-NEG edge serving due to platform constraints.
resource "google_cloud_run_v2_service_iam_member" "shim_invoker" {
  count    = local.edge_count
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.shim[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- serving-shim Cloud Run service (reachable only via the load balancer) ---
resource "google_cloud_run_v2_service" "shim" {
  count               = local.edge_count
  name                = "${var.name_prefix}-shim"
  project             = var.project_id
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account = google_service_account.shim[0].email
    scaling { max_instance_count = 10 }
    containers {
      image = var.serving_shim_image
      ports { container_port = 8080 }
      resources { limits = { cpu = "1", memory = "1Gi" } }
      env {
        name  = "STORAGE"
        value = "gcs"
      }
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.content.name
      }
      env {
        name  = "SITE_BASE_URL"
        value = var.site_base_url
      }
      env {
        name  = "SITE_HOSTS"
        value = local.site_host
      }
      env {
        name  = "AI_PATH_PREFIX"
        value = var.ai_path_prefix
      }
      env {
        name  = "CONTENT_CACHE_TTL"
        value = tostring(var.cdn_default_ttl_seconds)
      }
      env {
        name  = "ORIGIN_404_BEHAVIOR"
        value = var.origin_404_behavior
      }
      env {
        name  = "GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "CRAWL_TOPIC"
        value = google_pubsub_topic.crawl.name
      }
    }
  }
  depends_on = [google_project_service.apis]
}

# --- serverless NEG → the optimized backend service (Cloud CDN enabled) ---
resource "google_compute_region_network_endpoint_group" "shim_neg" {
  count                 = local.edge_count
  name                  = "${var.name_prefix}-shim-neg"
  project               = var.project_id
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = google_cloud_run_v2_service.shim[0].name
  }
  depends_on = [google_project_service.edge_apis]
}

resource "google_compute_backend_service" "optimized" {
  count                 = local.edge_count
  name                  = "${var.name_prefix}-optimized-backend"
  project               = var.project_id
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"
  enable_cdn            = true
  # Honor the shim's Cache-Control: markdown is cacheable; the no-store origin fallback
  # is never cached, so the self-heal surfaces once generation completes.
  cdn_policy {
    cache_mode  = "USE_ORIGIN_HEADERS"
    default_ttl = var.cdn_default_ttl_seconds
    client_ttl  = var.client_ttl
    cache_key_policy {
      include_host         = true
      include_protocol     = true
      include_query_string = true
    }
  }
  log_config {
    enable      = var.enable_cdn_logging
    sample_rate = var.cdn_log_sample_rate
  }
  backend {
    group = google_compute_region_network_endpoint_group.shim_neg[0].id
  }
  depends_on = [google_project_service.edge_apis]
}

# --- WASM edge plugin (detection only): UA match → rewrite :path ---
resource "google_network_services_wasm_plugin" "edge" {
  count           = local.edge_count
  name            = "${var.name_prefix}-edge"
  project         = var.project_id
  location        = "global"
  main_version_id = "v1"

  log_config {
    enable        = true
    min_log_level = "INFO"
  }

  versions {
    version_name = "v1"
    image_uri    = var.edge_plugin_image
    plugin_config_data = base64encode(jsonencode({
      ai_path_prefix     = var.ai_path_prefix
      ai_bot_user_agents = var.ai_bot_user_agents
    }))
  }
  depends_on = [google_project_service.edge_apis]
}
