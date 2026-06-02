#!/bin/zsh
# Independent Wire — daily production run (Mac Mini runner).
# Invoked by launchd. Deterministic: pull -> sync -> fetch -> run -> publish -> push site/.
set -euo pipefail

REPO="$HOME/Documents/independent-wire/repo-clone"
UV="$HOME/.local/bin/uv"
LOGDIR="$HOME/iw-logs"
mkdir -p "$LOGDIR"
TODAY="$(date +%F)"
LOG="$LOGDIR/run-$TODAY.log"

# launchd runs with a minimal environment: set a sane PATH, cd into the repo.
export PATH="$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$REPO"

trap 'echo "===== FAILED — $TODAY — $(date) — see log above =====" >> "$LOG"' ERR

{
  echo "===================================================="
  echo "Independent Wire daily run — $TODAY — $(date)"
  echo "===================================================="

  # The code reads os.environ directly (no dotenv) — load .env into the env.
  set -a; source .env; set +a

  echo "[1/6] git pull --rebase"
  git pull --rebase origin main

  echo "[2/6] uv sync (match deps to pulled code)"
  "$UV" sync

  echo "[3/6] fetch feeds"
  "$UV" run python scripts/fetch_feeds.py

  echo "[4/6] run pipeline (hydrated)"
  "$UV" run python scripts/run.py --hydrated

  echo "[5/6] publish"
  "$UV" run python scripts/publish.py

  echo "[6/6] commit + push site/ only"
  git add site/
  if git diff --cached --quiet; then
    echo "no site/ changes — nothing to commit"
  else
    git commit -m "content(site): daily publish $TODAY"
    git push origin main
    echo "pushed."
  fi

  echo "===== SUCCESS — $TODAY — $(date) ====="
} >> "$LOG" 2>&1
