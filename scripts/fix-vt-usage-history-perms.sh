#!/usr/bin/env bash
# fix-vt-usage-history-perms.sh — VTFIX-02E
#
# Restore append-safe ownership and mode on the shared VT usage history JSONL
# after manual cleanup, filter/replace, cp/mv, or any root-owned recreation.
#
# Safe properties:
#   - Metadata only (chown/chmod); never reads or writes file contents.
#   - Does not create the file if missing (empty history must be deliberate).
#   - Exits non-zero if file size changes (should never happen).
#
# Usage (typically as root):
#   sudo ./scripts/fix-vt-usage-history-perms.sh
#   sudo ./scripts/fix-vt-usage-history-perms.sh /var/lib/dns-tool/vt_usage_history.jsonl

set -euo pipefail

HISTORY_FILE="${1:-/var/lib/dns-tool/vt_usage_history.jsonl}"
OWNER="www-data"
GROUP="dns-tool"
MODE="0664"

if [[ ! -e "${HISTORY_FILE}" ]]; then
  echo "ERROR: ${HISTORY_FILE} does not exist; refusing to create an empty history file." >&2
  exit 1
fi

if [[ ! -f "${HISTORY_FILE}" ]]; then
  echo "ERROR: ${HISTORY_FILE} is not a regular file." >&2
  exit 1
fi

SIZE_BEFORE="$(stat -c '%s' "${HISTORY_FILE}")"

chown "${OWNER}:${GROUP}" "${HISTORY_FILE}"
chmod "${MODE}" "${HISTORY_FILE}"

SIZE_AFTER="$(stat -c '%s' "${HISTORY_FILE}")"
if [[ "${SIZE_BEFORE}" != "${SIZE_AFTER}" ]]; then
  echo "ERROR: file size changed during permission fix (${SIZE_BEFORE} -> ${SIZE_AFTER})." >&2
  exit 1
fi

# Metadata-only output for operator verification (no file contents).
stat -c 'OK owner=%U group=%G mode=%a size=%s mtime=%y path=%n' "${HISTORY_FILE}"
