"""
Daily database backup for QUO. See backend/RESTORE.md for how to restore
from whatever this produces - read that BEFORE you need it, not during an
actual incident.

Usage:
    python backup_db.py              # local backup, then an opportunistic
                                        # USB copy IF the designated backup
                                        # drive happens to be plugged in
    python backup_db.py --usb-now    # skip the local backup - just copy
                                        # today's (and any other) local
                                        # backups to the USB drive right now,
                                        # for use right after plugging it in

Local backups: backend/backups/local/<stem>_<YYYY-MM-DD_HHMM>.db, where
<stem> is taken from the live database's own filename (read from app.py's
SQLALCHEMY_DATABASE_URI line - see get_db_path() below), so this never
silently drifts from whatever file app.py actually opens.

USB backups: designating a USB drive as "the" backup drive is deliberate,
not automatic - see find_usb_drive()/claim_usb_drive() below for exactly
when this script will and won't write to a removable drive.

Log: backend/backups/backup_log.txt (appended to, one line per run - never
rewritten, so it's always safe to tail).

Scheduled daily via Windows Task Scheduler at 3:00 AM as
"QUO - Respaldo Diario de Base de Datos". See RESTORE.md for the exact
schtasks command used to create it, in case it ever needs recreating.
"""
import argparse
import ctypes
import os
import re
import shutil
import sqlite3
import string
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from backup_shared import BACKUPS_DIR, LOCAL_BACKUPS_DIR, LOG_PATH  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/

MARKER_FILENAME = "QUO_BACKUP_DRIVE.txt"
MARKER_COMMENT = (
    "Esta unidad fue designada como el disco USB de respaldo de la base de "
    "datos de QUO (Grupo Liquidambar).\n\n"
    "No borres este archivo: backend/scripts/backup_db.py lo usa para "
    "reconocer esta unidad automaticamente en cada respaldo. Si lo borras, "
    "los respaldos a esta unidad dejaran de copiarse - sin ningun otro "
    "aviso - hasta que vuelvas a crear un archivo con este mismo nombre "
    "aqui, o conectes esta unidad como la UNICA unidad removible presente "
    "y corras: python backup_db.py --usb-now (para que se designe de "
    "nuevo automaticamente).\n"
)

# Local retention: every daily backup for 30 days, then thinned to one per
# ISO calendar week for the following ~3 months (approximated as 90 days -
# adjust WEEKLY_WINDOW_DAYS if a stricter calendar-month rule is wanted
# later), then deleted entirely past that.
DAILY_WINDOW_DAYS = 30
WEEKLY_WINDOW_DAYS = DAILY_WINDOW_DAYS + 90

DRIVE_REMOVABLE = 2


# ---------------------------------------------------------------------------
# Locating the live database
# ---------------------------------------------------------------------------

def get_db_path():
    """Reads the path straight out of app.py's own SQLALCHEMY_DATABASE_URI
    line, without importing/executing app.py - so this backup script can't
    be brought down by an unrelated failure elsewhere in the app's
    module-level code (backups must basically never fail), and doesn't open
    its own SQLAlchemy connection just to read a config string. This is the
    exact same line app.py itself computes the path from, so the filename
    used here can never silently drift from what the live app actually
    opens."""
    app_py_path = os.path.join(BASE_DIR, "app.py")
    with open(app_py_path, encoding="utf-8") as f:
        source = f.read()
    match = re.search(
        r'SQLALCHEMY_DATABASE_URI"\]\s*=\s*"sqlite:///"\s*\+\s*os\.path\.join\(BASE_DIR,\s*"([^"]+)"\)',
        source,
    )
    if not match:
        raise RuntimeError(
            "No se pudo determinar la ruta de la base de datos a partir de "
            "backend/app.py (la linea de SQLALCHEMY_DATABASE_URI no tiene "
            "el formato esperado). Revisa app.py manualmente y ajusta "
            "get_db_path() en este script antes de confiar en sus respaldos."
        )
    return os.path.join(BASE_DIR, match.group(1))


# ---------------------------------------------------------------------------
# Local backup
# ---------------------------------------------------------------------------

def integrity_check(path):
    """Runs PRAGMA integrity_check via a FRESH connection to the backup
    FILE itself (never the live db) - this is what catches a backup that
    corrupted during creation, which is worse than no backup at all since
    it creates false confidence."""
    conn = sqlite3.connect(path)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    return result == "ok", result


def apply_local_retention(local_dir, stem, now=None):
    """Keeps every backup from the last DAILY_WINDOW_DAYS days, thins
    30-120 days old down to one per ISO calendar week (the earliest one
    that week, so re-running this is deterministic), and deletes anything
    older than WEEKLY_WINDOW_DAYS entirely. Returns (kept, deleted) filename
    lists."""
    now = now or datetime.now()
    pattern = re.compile(rf"^{re.escape(stem)}_(\d{{4}}-\d{{2}}-\d{{2}})_(\d{{4}})\.db$")

    entries = []
    for name in os.listdir(local_dir):
        m = pattern.match(name)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError:
            continue
        entries.append((d, name))
    entries.sort()  # oldest first, so "first seen this week" == earliest

    kept, deleted = [], []
    weekly_seen = set()
    for d, name in entries:
        age_days = (now - d).days
        if age_days <= DAILY_WINDOW_DAYS:
            kept.append(name)
            continue
        if age_days <= WEEKLY_WINDOW_DAYS:
            week_key = d.isocalendar()[:2]
            if week_key not in weekly_seen:
                weekly_seen.add(week_key)
                kept.append(name)
            else:
                deleted.append(name)
            continue
        deleted.append(name)

    for name in deleted:
        try:
            os.remove(os.path.join(local_dir, name))
        except OSError:
            pass

    return kept, deleted


def do_local_backup():
    db_path = get_db_path()
    result = {"db_path": db_path}

    if not os.path.exists(db_path):
        result.update(status="error", message=f"No se encontro la base de datos en {db_path}")
        return result

    os.makedirs(LOCAL_BACKUPS_DIR, exist_ok=True)
    stem = os.path.splitext(os.path.basename(db_path))[0]
    backup_name = f"{stem}_{datetime.now().strftime('%Y-%m-%d_%H%M')}.db"
    backup_path = os.path.join(LOCAL_BACKUPS_DIR, backup_name)

    try:
        source_conn = sqlite3.connect(db_path)
        try:
            dest_conn = sqlite3.connect(backup_path)
            try:
                source_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            source_conn.close()
    except Exception as e:
        result.update(status="error", message=f"Excepcion durante el respaldo: {e}", path=backup_path)
        return result

    integrity_ok, integrity_result = integrity_check(backup_path)
    size = os.path.getsize(backup_path)
    kept, deleted = apply_local_retention(LOCAL_BACKUPS_DIR, stem)

    result.update(
        path=backup_path, size=size, integrity=integrity_result,
        kept=len(kept), deleted=len(deleted), stem=stem,
    )
    if integrity_ok:
        result["status"] = "ok"
    else:
        result["status"] = "error"
        result["message"] = f"PRAGMA integrity_check fallo: {integrity_result}"
    return result


# ---------------------------------------------------------------------------
# USB step
# ---------------------------------------------------------------------------

def list_removable_drives():
    """Enumerates only genuinely removable drives (Windows DRIVE_REMOVABLE),
    never fixed/internal ones - this is what makes it safe to auto-claim an
    unmarked drive at all (see do_usb_step): the worst case is claiming the
    wrong USB stick, never a hard drive."""
    drives = []
    kernel32 = ctypes.windll.kernel32
    bitmask = kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not (bitmask & (1 << i)):
            continue
        root = f"{letter}:\\"
        try:
            drive_type = kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
        except Exception:
            continue
        if drive_type == DRIVE_REMOVABLE:
            drives.append(root)
    return drives


def find_marked_drive(drives):
    for root in drives:
        if os.path.exists(os.path.join(root, MARKER_FILENAME)):
            return root
    return None


def sync_local_backups_to_usb(usb_backups_dir):
    os.makedirs(usb_backups_dir, exist_ok=True)
    existing = set(os.listdir(usb_backups_dir))
    copied = []
    if not os.path.exists(LOCAL_BACKUPS_DIR):
        return copied
    for name in sorted(os.listdir(LOCAL_BACKUPS_DIR)):
        if not name.endswith(".db") or name in existing:
            continue
        shutil.copy2(os.path.join(LOCAL_BACKUPS_DIR, name), os.path.join(usb_backups_dir, name))
        copied.append(name)
    return copied


def do_usb_step(allow_claim):
    """allow_claim is True only for --usb-now (an explicit, human-triggered
    action right after plugging in a drive) - the unattended 3am scheduled
    run NEVER auto-claims a drive, only ever uses one that's already
    marked. Auto-claiming during an unattended run risks silently adopting
    someone's personal USB stick that happened to be plugged in overnight;
    requiring a human to either pre-mark the drive or run --usb-now with it
    as the only removable drive present is the actual safety guarantee
    here, not just the marker file by itself."""
    drives = list_removable_drives()
    marked_drive = find_marked_drive(drives)
    claimed_now = False

    if marked_drive is None and allow_claim:
        if len(drives) == 1:
            marked_drive = drives[0]
            try:
                with open(os.path.join(marked_drive, MARKER_FILENAME), "w", encoding="utf-8") as f:
                    f.write(MARKER_COMMENT)
                claimed_now = True
            except OSError as e:
                return {"status": "error", "message": f"No se pudo crear el archivo marcador en {marked_drive}: {e}"}
        elif len(drives) > 1:
            return {
                "status": "ambiguous",
                "message": (
                    f"Hay {len(drives)} unidades removibles sin marcador "
                    f"({', '.join(drives)}) - no se puede elegir automaticamente. "
                    f"Conecta solo la unidad correcta y vuelve a correr --usb-now, "
                    f"o crea manualmente {MARKER_FILENAME} en la unidad deseada."
                ),
            }

    if marked_drive is None:
        return {"status": "not_found", "message": "Unidad USB de respaldo no detectada."}

    try:
        usb_backups_dir = os.path.join(marked_drive, "backups")
        copied = sync_local_backups_to_usb(usb_backups_dir)
    except Exception as e:
        return {"status": "error", "message": f"Error copiando a la unidad USB: {e}", "drive": marked_drive}

    return {"status": "ok", "drive": marked_drive, "copied": len(copied), "claimed_now": claimed_now}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _clean(text):
    return str(text).replace("|", "/").replace("\n", " ").replace("\r", " ")


def append_log(local_result, usb_result):
    fields = {"timestamp": datetime.now().isoformat(timespec="seconds")}

    if local_result is None:
        fields["local_status"] = "skipped"
    else:
        fields["local_status"] = local_result.get("status", "error")
        for key in ("size", "integrity", "kept", "deleted"):
            if key in local_result:
                fields[f"local_{key}"] = _clean(local_result[key])
        if "message" in local_result:
            fields["local_message"] = _clean(local_result["message"])

    fields["usb_status"] = usb_result.get("status", "error")
    for key in ("copied", "drive"):
        if key in usb_result:
            fields[f"usb_{key}"] = _clean(usb_result[key])
    if "message" in usb_result:
        fields["usb_message"] = _clean(usb_result["message"])

    os.makedirs(BACKUPS_DIR, exist_ok=True)
    line = "|".join(f"{k}={v}" for k, v in fields.items())
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--usb-now", action="store_true",
        help="No hacer un respaldo local nuevo - solo copiar los respaldos locales existentes a la unidad USB de respaldo ahora mismo.",
    )
    args = parser.parse_args()

    if args.usb_now:
        usb_result = do_usb_step(allow_claim=True)
        line = append_log(None, usb_result)
        print(line)
        return 0  # a missing/ambiguous USB drive is never a script failure

    local_result = do_local_backup()
    usb_result = do_usb_step(allow_claim=False)
    line = append_log(local_result, usb_result)
    print(line)

    return 0 if local_result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
