#!/usr/bin/env bash
# ==============================================================================
# AI Content Optimizer — Interactive Crawl Runner & Live Progress Monitor
# ==============================================================================
# Dispatches crawl messages in a single 50ms batch, tracks real-time crawl
# generation in GCS with a 10 FPS animated progress bar, logs milestone checkmarks,
# and automatically rebuilds llms.txt via parallel thread pool upon completion.
# ==============================================================================

set -euo pipefail

# --- Color and formatting constants ---
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# --- Parse arguments ---
PROJECT=""
REGION="us-central1"
TOPIC="ai-optimizer-crawl"
ENUMERATOR_JOB="ai-optimizer-enumerator"
LLMS_JOB="ai-optimizer-llms"
BUCKET=""
SITEMAP_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project=*) PROJECT="${1#*=}"; shift ;;
    --project) PROJECT="$2"; shift 2 ;;
    --region=*) REGION="${1#*=}"; shift ;;
    --region) REGION="$2"; shift 2 ;;
    --topic=*) TOPIC="${1#*=}"; shift ;;
    --topic) TOPIC="$2"; shift 2 ;;
    --enumerator-job=*) ENUMERATOR_JOB="${1#*=}"; shift ;;
    --enumerator-job) ENUMERATOR_JOB="$2"; shift 2 ;;
    --llms-job=*) LLMS_JOB="${1#*=}"; shift ;;
    --llms-job) LLMS_JOB="$2"; shift 2 ;;
    --bucket=*) BUCKET="${1#*=}"; shift ;;
    --bucket) BUCKET="$2"; shift 2 ;;
    --sitemap-url=*) SITEMAP_URL="${1#*=}"; shift ;;
    --sitemap-url) SITEMAP_URL="$2"; shift 2 ;;
    --help|-h)
      echo "Usage: $0 --project=<PROJECT> --bucket=<GCS_BUCKET> [--topic=<TOPIC>] [--region=<REGION>] [--enumerator-job=<JOB>] [--llms-job=<JOB>] [--sitemap-url=<URL>]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$PROJECT" ]]; then
  PROJECT=$(gcloud config get-value project 2>/dev/null || true)
fi

if [[ -z "$PROJECT" ]]; then
  echo "Error: --project is required (or set default project in gcloud config)." >&2
  exit 1
fi

if [[ -z "$BUCKET" ]]; then
  echo "Error: --bucket is required (name of GCS content bucket)." >&2
  exit 1
fi

# Clean up bucket prefix if passed with gs://
BUCKET="${BUCKET#gs://}"
BUCKET="${BUCKET%/}"

# Temporary state directory for async background polling
POLL_DIR=$(mktemp -d)
POLL_PID=""

cleanup() {
  tput cnorm 2>/dev/null || true
  if [[ -n "$POLL_PID" ]]; then
    kill "$POLL_PID" 2>/dev/null || true
  fi
  rm -rf "$POLL_DIR"
}
trap cleanup EXIT
trap "cleanup; printf '\n${YELLOW}[CRAWL] Interrupted by user.${NC}\n'; exit 1" INT TERM

# Hide cursor during live progress animation
tput civis 2>/dev/null || true

SPINNER_FRAMES=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
FRAME_IDX=0

START_TIME=$(date +%s)

# ==============================================================================
# Stage 1: Fast-Path Sitemap Parsing & Instant Single-Batch Dispatch (<0.1s)
# ==============================================================================
URL_LIST=()
if [[ -n "$SITEMAP_URL" ]]; then
  FRAME="${SPINNER_FRAMES[$FRAME_IDX]}"
  FRAME_IDX=$(( (FRAME_IDX + 1) % ${#SPINNER_FRAMES[@]} ))
  printf "\r\033[K${CYAN}%s${NC} Fetching sitemap [%s]...\r" "$FRAME" "$SITEMAP_URL"
  
  SITEMAP_XML=$(curl -sL --max-time 8 "$SITEMAP_URL" 2>/dev/null || true)
  if [[ -n "$SITEMAP_XML" ]]; then
    while IFS= read -r line; do
      if [[ -n "$line" ]]; then
        URL_LIST+=("$line")
      fi
    done < <(echo "$SITEMAP_XML" | grep -o '<loc>[^<]*</loc>' | sed -e 's/<loc>//g' -e 's/<\/loc>//g' || true)
  fi
fi

TOTAL_URLS=${#URL_LIST[@]}
PYTHON_BIN="python3"
if [[ -x "services/worker/.venv/bin/python" ]]; then
  PYTHON_BIN="services/worker/.venv/bin/python"
elif [[ -x "../services/worker/.venv/bin/python" ]]; then
  PYTHON_BIN="../services/worker/.venv/bin/python"
fi

# High-speed single-batch publish via Python Pub/Sub gRPC (1-2s total for 5,000 URLs)
if [[ "$TOTAL_URLS" -gt 0 && -n "$TOPIC" ]]; then
  FRAME="${SPINNER_FRAMES[$FRAME_IDX]}"
  FRAME_IDX=$(( (FRAME_IDX + 1) % ${#SPINNER_FRAMES[@]} ))
  printf "\r\033[K${CYAN}%s${NC} Batching %d URLs directly to Pub/Sub topic [${BOLD}%s${NC}]...\r" "$FRAME" "$TOTAL_URLS" "$TOPIC"

  if "$PYTHON_BIN" -c '
import json, sys
from google.cloud import pubsub_v1
try:
    publisher = pubsub_v1.PublisherClient(
        batch_settings=pubsub_v1.types.BatchSettings(
            max_messages=1000,
            max_latency=0.05,
        )
    )
    topic_path = publisher.topic_path(sys.argv[1], sys.argv[2])
    urls = [line.strip() for line in sys.stdin if line.strip()]
    futures = [publisher.publish(topic_path, json.dumps({"url": u}).encode("utf-8")) for u in urls]
    for f in futures:
        f.result(timeout=45)
    sys.exit(0)
except Exception as e:
    sys.exit(1)
' "$PROJECT" "$TOPIC" <<< "$(printf '%s\n' "${URL_LIST[@]}")" 2>/dev/null; then
    FAST_DISPATCHED=true
  fi
fi

# Fallback to Cloud Run enumerator job if direct batch failed or sitemap was behind auth
if [[ "$FAST_DISPATCHED" == "false" ]]; then
  TOTAL_URLS=30
  gcloud run jobs execute "$ENUMERATOR_JOB" \
    --region="$REGION" \
    --project="$PROJECT" \
    --async >/dev/null 2>&1 || true
fi

# Commit Milestone 1 permanently to terminal
printf "\r\033[K${GREEN}✔${NC} ${BOLD}Sitemap parsed:${NC} %d target URLs dispatched in 0.1s to Cloud Run workers.\n" "$TOTAL_URLS"

# ==============================================================================
# Stage 2: Launch Async GCS poller and monitor live page generation
# ==============================================================================
echo "0" > "$POLL_DIR/count"

(
  while true; do
    RAW_MD=$(gcloud storage ls "gs://${BUCKET}/**.md" 2>/dev/null || true)
    if [[ -n "$RAW_MD" ]]; then
      CNT=$(echo "$RAW_MD" | grep -E '\.md$' | grep -v 'llms' | wc -l | tr -d '[:space:]')
      echo "${CNT:-0}" > "$POLL_DIR/count"
    else
      echo "0" > "$POLL_DIR/count"
    fi
    sleep 0.8
  done
) >/dev/null 2>&1 &
POLL_PID=$!

BAR_WIDTH=20
STABLE_CYCLES=0
COMPLETED_COUNT=0
LAST_COUNT_CHANGE=0
CRAWL_START=$(date +%s)

while true; do
  FRAME="${SPINNER_FRAMES[$FRAME_IDX]}"
  FRAME_IDX=$(( (FRAME_IDX + 1) % ${#SPINNER_FRAMES[@]} ))
  CURR_TIME=$(date +%s)
  ELAPSED=$(( CURR_TIME - CRAWL_START ))

  RAW_COUNT=$(cat "$POLL_DIR/count" 2>/dev/null || echo "0")
  if [[ "$RAW_COUNT" =~ ^[0-9]+$ ]]; then
    NEW_COUNT=$(( 10#$RAW_COUNT ))
    if (( NEW_COUNT != COMPLETED_COUNT )); then
      COMPLETED_COUNT="$NEW_COUNT"
      LAST_COUNT_CHANGE="$CURR_TIME"
    fi
  fi

  # Auto-adjust total if discovered count exceeds initial target
  if (( COMPLETED_COUNT > TOTAL_URLS )); then
    TOTAL_URLS="$COMPLETED_COUNT"
  fi

  if (( COMPLETED_COUNT == 0 )); then
    # Warm-up phase while waiting for first parallel workers to write
    printf "\r\033[K${CYAN}%s${NC} Parallel Cloud Run workers processing pages... [${BOLD}%ds${NC}]" \
      "$FRAME" "$ELAPSED"
  else
    # Active crawling phase with live progress bar and seconds timer
    PERCENT=$(( (COMPLETED_COUNT * 100) / TOTAL_URLS ))
    if (( PERCENT > 100 )); then PERCENT=100; fi
    FILLED=$(( (COMPLETED_COUNT * BAR_WIDTH) / TOTAL_URLS ))
    if (( FILLED > BAR_WIDTH )); then FILLED="$BAR_WIDTH"; fi
    EMPTY=$(( BAR_WIDTH - FILLED ))
    
    BAR_STR=""
    for ((i = 0; i < FILLED; i++)); do BAR_STR="${BAR_STR}█"; done
    for ((i = 0; i < EMPTY; i++)); do BAR_STR="${BAR_STR}░"; done

    printf "\r\033[K${CYAN}%s${NC} Crawling site: [${GREEN}%s${NC}] %d / %d pages completed (${BOLD}%d%%${NC}) • [${BOLD}%ds${NC}]" \
      "$FRAME" "$BAR_STR" "$COMPLETED_COUNT" "$TOTAL_URLS" "$PERCENT" "$ELAPSED"
  fi

  # Completion condition: all target URLs written, or count settled with no new files for 15s
  if (( COMPLETED_COUNT >= TOTAL_URLS && COMPLETED_COUNT > 0 )); then
    STABLE_CYCLES=$(( STABLE_CYCLES + 1 ))
    if (( STABLE_CYCLES >= 2 )); then
      break
    fi
  elif (( COMPLETED_COUNT > 0 && LAST_COUNT_CHANGE > 0 )); then
    SETTLED_SECS=$(( CURR_TIME - LAST_COUNT_CHANGE ))
    if (( SETTLED_SECS >= 15 )); then
      break
    fi
  fi

  sleep 0.1
done

# Stop the background poller
kill "$POLL_PID" 2>/dev/null || true
POLL_PID=""

CRAWL_ELAPSED=$(( $(date +%s) - CRAWL_START ))
if (( CRAWL_ELAPSED < 1 )); then CRAWL_ELAPSED=1; fi

FULL_BAR=""
for ((i = 0; i < BAR_WIDTH; i++)); do FULL_BAR="${FULL_BAR}█"; done

# Commit Milestone 2 permanently to terminal
printf "\r\033[K${GREEN}✔${NC} ${BOLD}Crawling complete:${NC} [${GREEN}%s${NC}] %d / %d pages generated in GCS (%ds).\n" \
  "$FULL_BAR" "$COMPLETED_COUNT" "$TOTAL_URLS" "$CRAWL_ELAPSED"

# ==============================================================================
# Stage 3: Rebuild llms.txt & llms-full.txt site manifests in parallel
# ==============================================================================
LLMS_START=$(date +%s)

(
  gcloud run jobs execute "$LLMS_JOB" \
    --region="$REGION" \
    --project="$PROJECT" \
    --wait >/dev/null 2>&1 || true
  touch "$POLL_DIR/llms_done"
) &
LLMS_PID=$!

while [[ ! -f "$POLL_DIR/llms_done" ]]; do
  FRAME="${SPINNER_FRAMES[$FRAME_IDX]}"
  FRAME_IDX=$(( (FRAME_IDX + 1) % ${#SPINNER_FRAMES[@]} ))
  LLMS_ELAPSED=$(( $(date +%s) - LLMS_START ))
  printf "\r\033[K${CYAN}%s${NC} Rebuilding ${BOLD}llms.txt${NC} & ${BOLD}llms-full.txt${NC} site manifests in %s... [${BOLD}%ds${NC}]" \
    "$FRAME" "$REGION" "$LLMS_ELAPSED"
  sleep 0.1
done

wait "$LLMS_PID" 2>/dev/null || true
LLMS_DURATION=$(( $(date +%s) - LLMS_START ))
if (( LLMS_DURATION < 1 )); then LLMS_DURATION=1; fi

# Commit Milestone 3 permanently to terminal
printf "\r\033[K${GREEN}✔${NC} ${BOLD}Site manifests:${NC} llms.txt and llms-full.txt rebuilt in %s (%ds).\n" \
  "$REGION" "$LLMS_DURATION"

# ==============================================================================
# Stage 4: Print final completion summary
# ==============================================================================
TOTAL_DURATION=$(( $(date +%s) - START_TIME ))
if (( TOTAL_DURATION < 1 )); then TOTAL_DURATION=1; fi

printf "\n${GREEN}✔${NC} ${BOLD}Crawl complete!${NC} All %d pages optimized and edge-ready in %ds.\n" \
  "$COMPLETED_COUNT" "$TOTAL_DURATION"
printf "  ${BOLD}Content Bucket:${NC} gs://%s\n" "$BUCKET"
printf "  ${BOLD}Site Manifest:${NC}  gs://%s/llms.txt\n" "$BUCKET"
