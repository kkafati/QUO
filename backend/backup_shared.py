"""Shared constants + the backup_log.txt parser, used by BOTH
backend/scripts/backup_db.py (which writes the log) and app.py's
/api/panel/resumen (which reads it for the backup-staleness indicator).

Deliberately its own module, imported by both of the above, rather than
having either of them import the other - app.py must never import
backup_db.py (that script imports `from app import app` to read the live
SQLALCHEMY_DATABASE_URI, so the reverse import would be circular).
"""
import os
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")
LOCAL_BACKUPS_DIR = os.path.join(BACKUPS_DIR, "local")
LOG_PATH = os.path.join(BACKUPS_DIR, "backup_log.txt")

# Local backups run daily, unconditionally - anything past 26h means the
# scheduled task didn't run, a real problem worth flagging immediately.
LOCAL_STALE_HOURS = 26
# The USB drive isn't reliably plugged in every day - only flag it once a
# full week has passed with no confirmed copy, a "remember to plug it in
# this week" nudge rather than an emergency.
USB_STALE_DAYS = 7


def _parse_log_line(line):
    fields = {}
    for pair in line.strip().split("|"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            fields[k] = v
    return fields


def get_last_backup_timestamps(log_path=LOG_PATH):
    """Scans every line of backup_log.txt (appended to, never rewritten) and
    returns (last_local_ok_iso, last_usb_ok_iso) - the timestamp of the most
    recent run where that side succeeded. Either can be None if it has never
    succeeded (or the log doesn't exist yet)."""
    last_local_ok = None
    last_usb_ok = None
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                fields = _parse_log_line(line)
                ts = fields.get("timestamp")
                if not ts:
                    continue
                if fields.get("local_status") == "ok":
                    last_local_ok = ts
                if fields.get("usb_status") == "ok":
                    last_usb_ok = ts
    return last_local_ok, last_usb_ok


def _is_stale(ts_iso, threshold, now):
    if not ts_iso:
        return True
    try:
        ts = datetime.fromisoformat(ts_iso)
    except ValueError:
        return True
    return (now - ts) > threshold


def get_backup_estado():
    """{ local: {last_backup_at, stale}, usb: {last_backup_at, stale} } -
    consumed by /api/panel/resumen. stale thresholds differ deliberately
    (see LOCAL_STALE_HOURS / USB_STALE_DAYS above)."""
    last_local_ok, last_usb_ok = get_last_backup_timestamps()
    now = datetime.now()
    return {
        "local": {
            "last_backup_at": last_local_ok,
            "stale": _is_stale(last_local_ok, timedelta(hours=LOCAL_STALE_HOURS), now),
        },
        "usb": {
            "last_backup_at": last_usb_ok,
            "stale": _is_stale(last_usb_ok, timedelta(days=USB_STALE_DAYS), now),
        },
    }
