#!/bin/zsh
# Independent Wire — daily production run (Mac Mini runner).
# Invoked by launchd. Deterministic: pull -> sync -> fetch -> run -> publish -> push site/.
set -euo pipefail

# Derive the repo root from this script's own location, so the runner is
# portable regardless of where the repo lives or how it is invoked. launchd
# passes an absolute script path; a manual run may pass a relative one. In zsh,
# ${0:A} absolutises + resolves symlinks; :h:h climbs from <repo>/scripts/
# daily_run.sh up to <repo>.
SCRIPT_PATH="${0:A}"
REPO="${SCRIPT_PATH:h:h}"
UV="$HOME/.local/bin/uv"
LOGDIR="$HOME/iw-logs"
mkdir -p "$LOGDIR"
TODAY="$(date +%F)"
LOG="$LOGDIR/run-$TODAY.log"

# launchd runs with a minimal environment: set a sane PATH, cd into the repo.
export PATH="$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$REPO"

# --- Branch guard (TASK-RUNNER-BRANCH-GUARD) --------------------------------
# The launchd runner builds whatever branch is checked out; on 2026-07-04 it ran
# on a leftover feature branch and the publish landed off-main (third occurrence
# of the leftover-checkout hazard). Refuse to run unless `main` is checked out —
# abort loudly BEFORE any fetch / pull / pipeline / publish / push. NEVER
# auto-checkout: a working tree left on a branch may be intentional, and a runner
# must not silently move it. This is a read-only branch check ("HEAD" for a
# detached checkout, "UNKNOWN" if git can't answer — both are != main → abort).
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo UNKNOWN)"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  {
    echo "===================================================="
    echo "ABORT — daily_run.sh — $TODAY — $(date)"
    echo "Refusing to run: checked-out branch is '$CURRENT_BRANCH', not 'main'."
    echo "No fetch / pull / pipeline / publish / push was performed."
    echo "Fix: cd '$REPO' && git checkout main  (the runner will NOT move your tree)."
    echo "===================================================="
  } | tee -a "$LOG" >&2
  exit 1
fi

# --- Stale git index.lock guard (TASK-DAILY-RUN-LOCK-GUARD) -----------------
# Two vacation incidents (2026-07-18, 2026-08-07) lost the morning publish to a
# stale zero-byte .git/index.lock left by an interrupted git process: step
# [6/6] `git add site/` died on "Unable to create index.lock: File exists" and
# nothing shipped. A lock is removed ONLY when it is both demonstrably
# abandoned (mtime older than STALE_LOCK_MIN) and provably unowned (no process
# named `git` anywhere on the box). Every other case — a young lock, a live git
# process, or an mtime we cannot read — REFUSES the run instead of pulling: a
# missed publish is recoverable by rerunning, a git index corrupted by racing a
# live operation is not. Deliberately placed AFTER the branch guard so a tree
# parked on a feature branch is refused without this ever touching its .git/.
STALE_LOCK_MIN=60
GIT_DIR_PATH="$(git rev-parse --absolute-git-dir 2>/dev/null || echo "$REPO/.git")"
LOCK="$GIT_DIR_PATH/index.lock"
if [[ -e "$LOCK" ]]; then
  # BSD stat/date (this runner is macOS-only). An unreadable mtime yields
  # age -1, which fails safe into the refusal branch — never into removal.
  LOCK_MTIME="$(stat -f %m "$LOCK" 2>/dev/null || echo "")"
  if [[ -n "$LOCK_MTIME" ]]; then
    LOCK_AGE_MIN=$(( ( $(date +%s) - LOCK_MTIME ) / 60 ))
    LOCK_AGE_TEXT="${LOCK_AGE_MIN} min (mtime $(date -r "$LOCK_MTIME"))"
  else
    LOCK_AGE_MIN=-1
    LOCK_AGE_TEXT="unknown — mtime unreadable"
  fi
  # `pgrep -x git` matches processes named exactly `git`, box-wide: a git
  # command running in ANY repo blocks removal. Conservative on purpose — the
  # cost of a false positive is one skipped run, the cost of a false negative
  # is a corrupted index. Wrapped in `if` so pgrep's exit 1 (= no match) does
  # not trip `set -e`.
  if pgrep -x git >/dev/null 2>&1; then
    GIT_RUNNING=yes
  else
    GIT_RUNNING=no
  fi

  if (( LOCK_AGE_MIN >= STALE_LOCK_MIN )) && [[ "$GIT_RUNNING" == "no" ]]; then
    # Remove first, report the verified outcome second — never log a removal
    # that did not happen (e.g. a permissions failure).
    if rm -f "$LOCK" && [[ ! -e "$LOCK" ]]; then
      {
        echo "===================================================="
        echo "GUARD — daily_run.sh — $TODAY — $(date)"
        echo "REMOVED stale git index.lock: $LOCK"
        echo "  age at removal: $LOCK_AGE_TEXT (threshold ${STALE_LOCK_MIN} min)"
        echo "  no process named 'git' was running — the lock was abandoned, not live."
        echo "Continuing with the run. Recurrence means the lock producer needs root-causing."
        echo "===================================================="
      } | tee -a "$LOG" >&2
    else
      {
        echo "===================================================="
        echo "ABORT — daily_run.sh — $TODAY — $(date)"
        echo "Stale git index.lock is removable by policy but rm FAILED: $LOCK"
        echo "  age: $LOCK_AGE_TEXT"
        echo "No fetch / pull / pipeline / publish / push was performed."
        echo "Fix: check ownership/permissions on '$LOCK', then rerun."
        echo "===================================================="
      } | tee -a "$LOG" >&2
      exit 1
    fi
  else
    {
      echo "===================================================="
      echo "ABORT — daily_run.sh — $TODAY — $(date)"
      echo "Refusing to run: git index.lock present and NOT provably stale: $LOCK"
      echo "  lock age:            $LOCK_AGE_TEXT (removal threshold ${STALE_LOCK_MIN} min)"
      echo "  git process running: $GIT_RUNNING"
      echo "A lock that is too young, held while git is live, or of unverifiable age"
      echo "may belong to a running operation — removing it could corrupt the index."
      echo "No fetch / pull / pipeline / publish / push was performed."
      echo "Fix: wait for the git operation to finish, or once certain no git is"
      echo "     running: rm '$LOCK'  (the runner will retry on the next trigger)."
      echo "===================================================="
    } | tee -a "$LOG" >&2
    exit 1
  fi
else
  echo "[guard] $(date) — no git index.lock at $LOCK — OK" >> "$LOG"
fi
# --- end stale git index.lock guard -----------------------------------------

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
  # ALL canonical extras, every time. `uv sync` is an exact sync: naming only
  # --extra multilingual PRUNES dev (pytest) and telegram from the venv on every
  # 06:00 run, so tests silently stop being runnable until someone resyncs by
  # hand (cost two test sessions, 2026-08-26 and 2026-08-27). Keep this list in
  # step with the project convention "never bare `uv sync`".
  "$UV" sync --extra dev --extra multilingual --extra telegram

  echo "[3/6] fetch feeds"
  "$UV" run python scripts/fetch_feeds.py

  echo "[4/6] run pipeline (hydrated)"
  "$UV" run python scripts/run.py --hydrated

  # Guard: run.py exits 0 even when every topic fails. A run that produced zero
  # Topic Packages is a failure, not a success — never publish a no-op. (N) is
  # NULL_GLOB so an empty match yields an empty array instead of a zsh error.
  # `false` routes through the existing ERR trap (writes the FAILED marker) and,
  # under `set -e`, exits non-zero before publish/commit/push run.
  tps=( "output/$TODAY"/tp-*.json(N) )
  if (( ${#tps} == 0 )); then
    echo "ERROR: zero Topic Packages produced for $TODAY — treating run as FAILED; skipping publish/push"
    false
  fi

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

  # Chained, NON-FATAL German translation. Runs only after the English run has
  # already published, pushed, and logged SUCCESS above — so a translation
  # failure can never flip the English run to FAILED. The `|| echo ...` swallows
  # any non-zero exit (keeping `set -e`/the ERR trap from aborting). The wrapper
  # is invoked whole: it has its own .env sourcing, zero-TP guard, publish_de,
  # logging, and git pull/commit/push of site/de/. Translation stays a separate
  # process — it is NEVER imported into run.py/the pipeline. This replaces the
  # standalone org.independent-wire.translate-de LaunchAgent, whose fixed-clock
  # trigger raced the variable English end time.
  echo "[chained] German translation"
  zsh "$REPO/scripts/translate_de_run.sh" || echo "WARN: German translation step failed — see iw-logs/translate_de-$TODAY.log"
} >> "$LOG" 2>&1
