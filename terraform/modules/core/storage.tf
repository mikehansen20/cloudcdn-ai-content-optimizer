# Content bucket for regional storage co-located with the Vertex region.
# The build plane writes generated content here while the serving plane reads.
# Source hash and validator values are stored in object metadata without requiring a database.

resource "google_storage_bucket" "content" {
  name                        = local.content_bucket
  project                     = var.project_id
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = var.bucket_force_destroy
  labels                      = local.labels

  # Expire orphaned pending marker objects.
  lifecycle_rule {
    condition {
      age            = max(1, ceil(var.pending_marker_ttl / 86400))
      matches_prefix = ["pending/"]
    }
    action {
      type = "Delete"
    }
  }
}
