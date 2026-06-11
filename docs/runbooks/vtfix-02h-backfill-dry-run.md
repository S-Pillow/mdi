# VTFIX-02H — Daily-History Metadata Backfill (Dry-Run)

**Status:** Discovery and dry-run only. **No runtime write** without explicit
operator approval in a follow-on ticket.

## Purpose

Historical `vt_daily_history.json` entries may use legacy shapes (integer totals,
partial dicts) from before VTFIX-02D schema v2. The dashboard normalizes these at
read time, but on-disk history may remain legacy-shaped. VTFIX-02H analyzes whether
a metadata-only backfill can persist schema v2 without changing quota totals or
assigning per-tool attribution without evidence.

## Runtime files (read-only for dry-run)

| File | Role |
|---|---|
| `/var/lib/dns-tool/vt_daily_history.json` | Per-day quota totals and tool buckets |
| `/var/lib/dns-tool/vt_usage_history.jsonl` | Optional attribution evidence (`tool_name`, timestamps) |
| `/var/lib/dns-tool/vt_usage.json` | Live counter — **never modified by backfill** |

## Dry-run procedure

1. Confirm working tree clean; do **not** deploy or restart services.
2. Record runtime metadata only (mtime, size, line count). Do not print raw contents.
3. Run dry-run script from repo root:

```bash
cd /root/mdi
python3 scripts/vtfix-02h-daily-history-backfill-dry-run.py
```

Optional machine-readable output:

```bash
python3 scripts/vtfix-02h-daily-history-backfill-dry-run.py --json
```

Custom paths (staging copies only):

```bash
python3 scripts/vtfix-02h-daily-history-backfill-dry-run.py \
  --daily-file /tmp/vt_daily_history.json \
  --jsonl-file /tmp/vt_usage_history.jsonl
```

4. Review proposed plan table:
   - **high** + `write? yes` — schema normalization only; totals preserved.
   - **manual_review** — do not write until operator resolves conflict.
5. Re-check runtime metadata unchanged after dry-run.

## Backfill rules ( enforced by script )

1. Preserve existing daily totals unless JSONL evidence proves a correction (none auto-applied).
2. Preserve unknown values as `tools.legacy`.
3. Do **not** assign legacy/unattributed JSONL records to MDI or VT Bulk without `tool_name`.
4. Legacy dict entries with `tool: mdi` may normalize to MDI bucket (field evidence).
5. Conflicting JSONL vs daily totals → `manual_review`.
6. Never modify `vt_usage.json` or `vt_usage_history.jsonl`.

## Tests

```bash
cd /root/mdi/backend
python3 -m pytest tests/test_vtfix_02h_backfill_dry_run.py -v
```

## Actual backfill execution

**Approved runtime normalization (VTFIX-02H-RUNTIME):** operator-approved write
mode normalizes five high-confidence dates only:

```bash
python3 /root/mdi/scripts/vtfix-02h-daily-history-backfill-dry-run.py --write-approved-normalization
```

Requires production path `/var/lib/dns-tool/vt_daily_history.json` (no
`--daily-file` override). Creates timestamped backup under
`/var/lib/dns-tool/backups/vtfix-02h-runtime-*`. Does **not** modify
`vt_usage.json` or `vt_usage_history.jsonl`.

Manual-review dates (`2026-06-03`, `2026-06-07`) and existing v2 date
(`2026-06-11`) are preserved unchanged.

**Not in scope for dry-run ticket.** Requires:

- Operator review of dry-run report
- Explicit approval
- Separate approved ticket with `--write` support, backup, and coordinated deploy window

## Related tickets

- VTFIX-02D — schema v2 forward writes (closed)
- VTFIX-02G — dashboard per-tool trend visibility (closed)
- VTFIX-02H — this dry-run / optional backfill
- MDI-43 — not started
