# Enumerator + llms.txt Cloud Run jobs and the Cloud Scheduler jobs that drive
# them. A sitemap crawl is a scheduled batch: Scheduler triggers
# the enumerator job (fans the sitemap into per-URL crawl messages), then a second,
# delayed Scheduler job rebuilds llms.txt / llms-full.txt from the stored pages.
# Both jobs reuse the worker image with a command override; the
# renderer is not involved. IAM uses least-privilege service accounts.

# --- service accounts (per-job) ---
resource "google_service_account" "enumerator" {
  account_id   = "${var.name_prefix}-enumerator"
  project      = var.project_id
  display_name = "AI Content Optimizer enumerator (sitemap -> crawl topic)"
}

resource "google_service_account" "builder" {
  account_id   = "${var.name_prefix}-builder"
  project      = var.project_id
  display_name = "AI Content Optimizer llms.txt builder"
}

resource "google_service_account" "scheduler" {
  account_id   = "${var.name_prefix}-scheduler"
  project      = var.project_id
  display_name = "Cloud Scheduler invoker for the offline jobs"
}

# --- enumerator job: python -m cascade.enumerator -> publishes crawl messages ---
resource "google_cloud_run_v2_job" "enumerator" {
  name                = "${var.name_prefix}-enumerator"
  project             = var.project_id
  location            = var.region
  deletion_protection = false
  labels              = local.labels

  template {
    template {
      service_account = google_service_account.enumerator.email
      max_retries     = 1
      containers {
        image   = var.worker_image
        command = ["python", "-m", "cascade.enumerator"]
        resources { limits = { cpu = "1", memory = "1Gi" } }
        env {
          name  = "GCP_PROJECT"
          value = var.project_id
        }
        env {
          name  = "CRAWL_TOPIC"
          value = google_pubsub_topic.crawl.name
        }
        env {
          name  = "SITEMAP_URL"
          value = local.sitemap_url
        }
        env {
          name  = "INCLUDE_PATHS"
          value = join(",", var.include_paths)
        }
        env {
          name  = "EXCLUDE_PATHS"
          value = join(",", var.exclude_paths)
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
  }
  depends_on = [google_project_service.apis]
}

# --- llms builder job: python -m cascade.llms -> writes llms.txt / llms-full.txt ---
resource "google_cloud_run_v2_job" "llms" {
  name                = "${var.name_prefix}-llms"
  project             = var.project_id
  location            = var.region
  deletion_protection = false
  labels              = local.labels

  template {
    template {
      service_account = google_service_account.builder.email
      max_retries     = 1
      containers {
        image   = var.worker_image
        command = ["python", "-m", "cascade.llms"]
        resources { limits = { cpu = "1", memory = "2Gi" } }
        env {
          name  = "STORAGE"
          value = "gcs"
        }
        env {
          name  = "GCS_BUCKET"
          value = google_storage_bucket.content.name
        }
        env {
          name  = "SITE_TITLE"
          value = var.site_title
        }
      }
    }
  }
  depends_on = [google_project_service.apis]
}

# --- job IAM ---
resource "google_pubsub_topic_iam_member" "enumerator_publishes_crawl" {
  topic  = google_pubsub_topic.crawl.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.enumerator.email}"
}

# The llms builder lists + reads every page and rewrites llms.txt / llms-full.txt on
# every run (overwrite). That is objectUser (get/list/create/delete/update) rather than
# objectAdmin (no object setIamPolicy). objectCreator alone can't overwrite.
resource "google_storage_bucket_iam_member" "builder_bucket" {
  bucket = google_storage_bucket.content.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.builder.email}"
}

# The scheduler SA runs each job via the Cloud Run Admin API (jobs.run).
resource "google_cloud_run_v2_job_iam_member" "scheduler_runs_enumerator" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.enumerator.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_runs_llms" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.llms.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

# --- Cloud Scheduler: crawl (rebuild_schedule) + a delayed llms.txt rebuild ---
locals {
  run_job_uri = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs"
}

resource "google_cloud_scheduler_job" "crawl" {
  name        = "${var.name_prefix}-crawl"
  project     = var.project_id
  region      = var.region
  schedule    = var.rebuild_schedule
  description = "Trigger the enumerator: fan the sitemap into per-URL crawl messages."

  http_target {
    http_method = "POST"
    uri         = "${local.run_job_uri}/${google_cloud_run_v2_job.enumerator.name}:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.scheduler_runs_enumerator]
}

resource "google_cloud_scheduler_job" "llms" {
  name        = "${var.name_prefix}-llms"
  project     = var.project_id
  region      = var.region
  schedule    = var.llms_schedule
  description = "Rebuild llms.txt / llms-full.txt from the stored pages (delayed after the crawl)."

  http_target {
    http_method = "POST"
    uri         = "${local.run_job_uri}/${google_cloud_run_v2_job.llms.name}:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.scheduler_runs_llms]
}
