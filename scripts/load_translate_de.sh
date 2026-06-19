#!/bin/zsh
# Loader for the org.independent-wire.translate-de LaunchAgent.
#
# Installs the plist into ~/Library/LaunchAgents and bootstraps it for the GUI domain so
# it fires daily at 07:30, after the 06:00 production run. PERSISTENT/recurring — it does
# NOT self-terminate (it is the live German-translation feature). Idempotent: re-running
# re-installs cleanly.
#
# Operator authorizes installation — run this script yourself when ready:
#     ./scripts/load_translate_de.sh
set -uo pipefail

LABEL="org.independent-wire.translate-de"
SCRIPT_DIR="${0:A:h}"
SRC="${SCRIPT_DIR}/${LABEL}.plist"
DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
UID_NUM="$(id -u)"

chmod +x "${SCRIPT_DIR}/translate_de_run.sh"
/bin/cp -f "$SRC" "$DST"

# clear any prior instance, then bootstrap + enable
/bin/launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
/bin/launchctl enable "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
/bin/launchctl bootstrap "gui/${UID_NUM}" "$DST" \
  || /bin/launchctl load "$DST"

echo "loaded ${LABEL}:"
/bin/launchctl list | grep -i translate-de \
  || echo "(not listed yet — check 'launchctl print gui/${UID_NUM}/${LABEL}')"
echo "scheduled: daily 07:30 (after the 06:00 production run). Persistent/recurring."
echo "to unload:  /bin/launchctl bootout gui/${UID_NUM}/${LABEL} && rm -f \"$DST\""
