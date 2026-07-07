#!/bin/zsh
# Independent Wire — intraday collector window (Mac Mini runner).
# Invoked by launchd (org.independent-wire.collector) at 10/14/18/22/02 local.
#
# Deterministic, fetch-only: fetch the RSS delta and dedup-append it into the
# NEXT 06:00 run's store (raw/{target}/feeds.json). NO git pull, NO uv sync, NO
# publish, NO push — a collector failure must never endanger the 06:00 main run.
# The collector has its OWN LaunchAgent and log; missed windows are self-healing:
# the next window (or the 06:00 final delta fetch) picks up the items.
set -euo pipefail

# Repo root from this script's own location (${0:A} absolutises + resolves
# symlinks; :h:h climbs <repo>/scripts/collector_run.sh -> <repo>). Same idiom
# as daily_run.sh so the wrapper is portable.
SCRIPT_PATH="${0:A}"
REPO="${SCRIPT_PATH:h:h}"
UV="$HOME/.local/bin/uv"
LOGDIR="$HOME/iw-logs"
mkdir -p "$LOGDIR"
# Wrapper-level (launchd) trail, one file per day appended by every window. The
# per-window data line (fetched / new-after-dedup / wall) is written separately
# by fetch_feeds.py into collector-{target-date}.log.
LOG="$LOGDIR/collector-run-$(date +%F).log"

export PATH="$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$REPO"

# --- Branch guard -----------------------------------------------------------
# launchd builds whatever branch is checked out (leftover-checkout hazard hit
# the daily runner 3x). The collector writes the raw/ store the 06:00 run reads,
# so a broken feature-branch fetch could corrupt it. Refuse unless main is
# checked out; NEVER auto-checkout. A skip is self-healing (the delta defers to
# the next window / the 06:00 fetch), so exit 0 — not a failure to retry-storm.
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo UNKNOWN)"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  echo "$(date) SKIP collector: branch '$CURRENT_BRANCH' != main (no fetch)" \
    | tee -a "$LOG" >&2
  exit 0
fi

# Load .env if present so an enabled IW_CLUSTER_TRANSLATE (+ CT2 dir / spiece)
# reaches the Phase-3 prewarm. Fetch itself needs no keys; a missing .env is fine
# and the flag stays unset -> prewarm no-op.
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

{
  echo "===== collector window — $(date) — branch=$CURRENT_BRANCH ====="
  "$UV" run python scripts/fetch_feeds.py --collector-window
  echo "===== collector window done — $(date) ====="
} >> "$LOG" 2>&1
