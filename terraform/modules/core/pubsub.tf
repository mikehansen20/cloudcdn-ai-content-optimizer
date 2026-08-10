# Pub/Sub. The crawl topic carries per-URL messages from
# the enumerator to the worker; the dead-letter topic captures poison URLs. The
# worker push subscription lives with the worker (cloudrun.tf) since it needs the
# service URL. A retention subscription keeps dead-lettered messages inspectable.

resource "google_pubsub_topic" "crawl" {
  name       = "${var.name_prefix}-crawl"
  project    = var.project_id
  labels     = local.labels
  depends_on = [google_project_service.apis]
}

resource "google_pubsub_topic" "deadletter" {
  name       = "${var.name_prefix}-deadletter"
  project    = var.project_id
  labels     = local.labels
  depends_on = [google_project_service.apis]
}

resource "google_pubsub_subscription" "deadletter" {
  name                       = "${var.name_prefix}-deadletter-sub"
  project                    = var.project_id
  topic                      = google_pubsub_topic.deadletter.id
  message_retention_duration = "604800s" # keep dead-lettered messages 7 days for inspection
  labels                     = local.labels
}
