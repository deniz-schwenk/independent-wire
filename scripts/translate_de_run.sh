#!/bin/zsh
# German translation wrapper (standalone org.independent-wire.translate-de retired).
#
# Post-pipeline German feature, invoked by CHAINING: daily_run.sh calls it as its
# final, non-fatal step, right after the English run publishes, pushes, and logs
# SUCCESS — so it always runs off the English run's actual completion. (The old
# fixed 07:00/07:30 LaunchAgent trigger raced the variable English end time and
# was retired.) It reads the finished production run state READ-ONLY, writes
# German JSON to output/<date>/de/, then renders the German pages and pushes the
# German site (site/de/). It NEVER touches the pipeline (scripts/run.py) or the
# English site/; the English site is pushed independently by daily_run.sh. Can
# also be run by hand to backfill a missed day.
#
# Flow: translate (translate_de.py) -> render+publish German pages (publish_de.py -> site/de/)
# -> commit + push site/de/ only. The day's-run guard lives in scripts/translate_de.py: if no
# completed TPs are present (run absent/incomplete), it logs and exits 0 without doing anything.
set -uo pipefail

# Derive the repo root from this script's own location (zsh ${0:A} absolutises + resolves
# symlinks; :h:h climbs <repo>/scripts/translate_de_run.sh -> <repo>), mirroring daily_run.sh.
SCRIPT_PATH="${0:A}"
REPO="${SCRIPT_PATH:h:h}"
PYBIN="$REPO/.venv/bin/python"
LOGDIR="$HOME/iw-logs"
mkdir -p "$LOGDIR"
TODAY="$(date +%F)"
LOG="$LOGDIR/translate_de-$TODAY.log"

# launchd runs with a minimal environment: set a sane PATH, cd into the repo.
export PATH="$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$REPO" || exit 1

rc=0
{
  echo "===================================================="
  echo "Independent Wire — German translation — $TODAY — $(date)"
  echo "===================================================="

  # Load repo secrets so the billed fallback providers (steps 2-4) have their keys.
  # The happy path (Ollama-Cloud, step 1) needs no key; these only matter if Ollama fails.
  set -a; [[ -f .env ]] && source .env; set +a

  "$PYBIN" scripts/translate_de.py
  rc=$?

  # After translation completes, render the German pages and push the German site. This is
  # the translation feature's OWN post-run flow — never wired into scripts/run.py. It commits
  # ONLY site/de/, so the English site/ (pushed independently by daily_run.sh) is untouched.
  if [[ $rc -eq 0 ]]; then
    echo "[render + publish German pages -> site/de/]"
    if "$PYBIN" scripts/publish_de.py; then
      git add site/de
      if git diff --cached --quiet; then
        echo "no site/de/ changes — nothing to commit"
      else
        git commit -m "content(site/de): German translation $TODAY"
        git pull --rebase origin main || true
        git push origin main && echo "pushed site/de/"
      fi
    else
      echo "publish_de failed — German site not pushed"
    fi
  fi

  echo "===== translate_de exit $rc — $TODAY — $(date) ====="
} >> "$LOG" 2>&1

exit $rc
