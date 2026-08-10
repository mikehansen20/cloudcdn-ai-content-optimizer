# Cloud Run services + the worker push subscription.
# Both services require auth (no allUsers). The renderer is reachable only by the
# worker SA (ID token); the worker only by the Pub/Sub push SA (OIDC). Runtime IAM
# uses least-privilege service accounts for each service.

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  pubsub_agent = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
  site_host    = replace(replace(var.site_base_url, "https://", ""), "http://", "")
}

# --- service accounts (per-service) ---
resource "google_service_account" "worker" {
  account_id   = "${var.name_prefix}-worker"
  project      = var.project_id
  display_name = "AI Content Optimizer worker"
}

# The renderer is purely internal (URL in, DOM out) and holds NO project/bucket/Vertex
# permissions by design. It is only referenced as the renderer service's identity and
# invoked by the worker (see worker_invokes_renderer). Deliberately no IAM member bindings.
resource "google_service_account" "renderer" {
  account_id   = "${var.name_prefix}-renderer"
  project      = var.project_id
  display_name = "AI Content Optimizer renderer"
}

resource "google_service_account" "pubsub_invoker" {
  account_id   = "${var.name_prefix}-pubsub-invoker"
  project      = var.project_id
  display_name = "Pub/Sub push invoker (OIDC)"
}

# --- renderer service (auth-required, called by the worker) ---
resource "google_cloud_run_v2_service" "renderer" {
  name                = "${var.name_prefix}-renderer"
  project             = var.project_id
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account = google_service_account.renderer.email
    scaling { max_instance_count = 3 }
    containers {
      image = var.renderer_image
      ports { container_port = 8080 }
      resources { limits = { cpu = "1", memory = "2Gi" } }
    }
  }
  depends_on = [google_project_service.apis]
}

# --- worker service ---
resource "google_cloud_run_v2_service" "worker" {
  name                = "${var.name_prefix}-worker"
  project             = var.project_id
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account                  = google_service_account.worker.email
    max_instance_request_concurrency = var.worker_concurrency
    scaling {
      min_instance_count = var.worker_min_instances
      max_instance_count = var.worker_max_instances
    }
    containers {
      image = var.worker_image
      ports { container_port = 8080 }
      resources {
        limits            = { cpu = "1", memory = "1Gi" }
        startup_cpu_boost = true
        cpu_idle          = true
      }
      env {
        name  = "STORAGE"
        value = "gcs"
      }
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.content.name
      }
      env {
        name  = "RENDERER_URL"
        value = google_cloud_run_v2_service.renderer.uri
      }
      env {
        name  = "RENDERER_AUTH"
        value = "1"
      }
      env {
        name  = "MODEL"
        value = "vertex"
      }
      env {
        name  = "GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "VERTEX_LOCATION"
        value = local.vertex_location
      }
      env {
        name  = "MODEL_ID"
        value = var.gemini_model
      }
      env {
        name  = "SITE_HOSTS"
        value = local.site_host
      }
      env {
        name  = "CRAWLER_USER_AGENT"
        value = var.crawler_user_agent
      }
    }
  }
  depends_on = [google_project_service.apis]
}

# --- service-to-service + runtime IAM ---
resource "google_cloud_run_v2_service_iam_member" "worker_invokes_renderer" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.renderer.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_cloud_run_v2_service_iam_member" "pubsub_invokes_worker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.worker.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pubsub_invoker.email}"
}

# Vertex: the narrowest PREDEFINED role that permits online prediction. Custom roles are
# avoided here because some org policies restrict custom-role creation, and standard predefined
# roles maximize out-of-the-box deployability. Customers requiring tighter access can
# swap this for a custom role granting only
# `aiplatform.endpoints.predict` (documented in the security & permissions guide).
resource "google_project_iam_member" "worker_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

# Content bucket: the worker reads prior object metadata (conditional fetch + hash-skip)
# and writes/overwrites generated pages. That is objectUser (get/list/create/
# delete/update) rather than objectAdmin (which also grants object setIamPolicy/getIamPolicy).
# objectCreator alone is insufficient: it cannot overwrite an existing object.
resource "google_storage_bucket_iam_member" "worker_bucket" {
  bucket = google_storage_bucket.content.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.worker.email}"
}

# --- worker push subscription (OIDC) with dead-letter ---
resource "google_service_account_iam_member" "pubsub_agent_tokencreator" {
  service_account_id = google_service_account.pubsub_invoker.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.pubsub_agent
}

resource "google_pubsub_topic_iam_member" "dlq_publisher" {
  topic  = google_pubsub_topic.deadletter.id
  role   = "roles/pubsub.publisher"
  member = local.pubsub_agent
}

resource "google_pubsub_subscription" "worker_push" {
  name                 = "${var.name_prefix}-worker-push"
  project              = var.project_id
  topic                = google_pubsub_topic.crawl.id
  ack_deadline_seconds = 600
  labels               = local.labels

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.worker.uri}/pubsub"
    oidc_token {
      service_account_email = google_service_account.pubsub_invoker.email
    }
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.deadletter.id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "20s"
    maximum_backoff = "600s"
  }

  depends_on = [google_cloud_run_v2_service_iam_member.pubsub_invokes_worker]
}

resource "google_pubsub_subscription_iam_member" "dlq_subscriber" {
  subscription = google_pubsub_subscription.worker_push.name
  project      = var.project_id
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent
}
