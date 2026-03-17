#!/usr/bin/env python3
"""
Last Chance Cleanup Script

Deletes items from the "Last Chance" collection across all Plex libraries,
removes them from Radarr/Sonarr (with file deletion), and sends a Gotify notification.

Run on the 1st of each month BEFORE Kometa, which then rebuilds the collection
from any newly tagged "leaving" items.

Usage:
    python lastchance.py                          # Execute deletions
    python lastchance.py --dry-run                # Preview only
    python lastchance.py --env-file /path/.env    # Load env from file
    python lastchance.py --no-notify              # Skip Gotify
    python lastchance.py --no-delete-files        # Remove from *arr but keep files
    python lastchance.py --import-exclude         # Add *arr import exclusion

Environment Variables (uses same KOMETA_ prefix as Kometa):
    KOMETA_PLEXURL, KOMETA_PLEXTOKEN
    KOMETA_RADARRURL, KOMETA_RADARRTOKEN
    KOMETA_SONARRURL, KOMETA_SONARRTOKEN
    KOMETA_GOTIFYURL, KOMETA_GOTIFYTOKEN (optional)
"""

import os
import sys
import argparse
import logging
import platform
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests
from plexapi.server import PlexServer

VERSION = "1.0.0"
COLLECTION_NAME = "Last Chance"
WIDTH = 100
CONFIG_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = CONFIG_DIR / "logs"
LOG_FILE = "lastchance.log"
LOG_BACKUPS = 9
DEFAULT_ENV = CONFIG_DIR / ".env"

# Secrets to redact — populated at runtime after env vars are loaded
_secrets: list[str] = []

# Maps Plex library type -> (GUID provider, *arr catalog key)
ARR_CONFIG = {
    "movie": {
        "provider": "tmdb",
        "key": "tmdbId",
        "endpoint": "movie",
        "label": "Radarr",
        "url_env": "KOMETA_RADARRURL",
        "token_env": "KOMETA_RADARRTOKEN",
    },
    "show": {
        "provider": "tvdb",
        "key": "tvdbId",
        "endpoint": "series",
        "label": "Sonarr",
        "url_env": "KOMETA_SONARRURL",
        "token_env": "KOMETA_SONARRTOKEN",
    },
}


def _redact_filter(record):
    """Redact any known secrets from log messages."""
    if _secrets:
        msg = record.getMessage()
        for secret in _secrets:
            msg = msg.replace(secret, "<redacted>")
        record.msg = msg
        record.args = None
    return True


class KometaFormatter(logging.Formatter):
    """Fixed-width log formatter matching Kometa's style."""

    def __init__(self, width=WIDTH, include_timestamp=True):
        super().__init__()
        self.width = width
        self.include_timestamp = include_timestamp

    def format(self, record):
        msg = record.getMessage()
        level = f"[{record.levelname}]"

        if msg and len(set(msg)) == 1 and msg[0] in "=-~*":
            padded = f"|{msg[0] * self.width}|"
        elif getattr(record, "center", False) and msg:
            padded = f"|{msg:^{self.width}}|"
        else:
            padded = f"| {msg:<{self.width - 1}}|"

        if self.include_timestamp:
            ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
            ms = f",{int(record.msecs):03d}"
            file_ref = f"[{record.filename}:{record.lineno}]"
            return f"[{ts}{ms}] {file_ref:<28s}{level:<11s}{padded}"
        return f"{level:<11s}{padded}"


def setup_logging():
    """Configure logging to match Kometa's log pattern — file + console."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / LOG_FILE

    log = logging.getLogger("lastchance")
    log.setLevel(logging.DEBUG)
    log.addFilter(_redact_filter)

    # File handler — rotates per run (like Kometa's meta.log)
    def log_namer(default_name):
        """Rename rotated logs: lastchance.log.1 -> lastchance-1.log"""
        parts = Path(default_name).name.rsplit(".", 2)
        if len(parts) == 3:
            base, ext, num = parts
            return str(LOG_DIR / f"{base}-{num}.{ext}")
        return default_name

    file_handler = RotatingFileHandler(
        log_path,
        backupCount=LOG_BACKUPS,
        encoding="utf-8",
    )
    file_handler.namer = log_namer
    if log_path.exists() and log_path.stat().st_size > 0:
        file_handler.doRollover()
    file_handler.setFormatter(KometaFormatter(include_timestamp=True))
    log.addHandler(file_handler)

    # Console handler — INFO only (DEBUG goes to file only, like Kometa)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(KometaFormatter(include_timestamp=False))
    log.addHandler(console_handler)

    return log


log = setup_logging()


def _get_memory_gb():
    """Return (total, available) memory in GB."""
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                parts = line.split()
                if parts[0] in ("MemTotal:", "MemAvailable:"):
                    info[parts[0]] = int(parts[1])  # kB
            return round(info["MemTotal:"] / (1 << 20)), round(
                info["MemAvailable:"] / (1 << 20)
            )
    except (OSError, KeyError):
        return None, None


def _get_priority():
    """Return the process scheduling priority as a label."""
    try:
        nice = os.nice(0)
        if nice <= -10:
            return "high"
        if nice >= 10:
            return "low"
        return "normal"
    except OSError:
        return "normal"


# Maps argparse dest -> CLI flag name
_ARG_ENV_MAP = [
    ("dry_run", "--dry-run"),
    ("env_file", "--env-file"),
    ("no_notify", "--no-notify"),
    ("no_delete_files", "--no-delete-files"),
    ("import_exclude", "--import-exclude"),
]

_SECRET_ENV_VARS = [
    "KOMETA_PLEXURL",
    "KOMETA_PLEXTOKEN",
    "KOMETA_RADARRURL",
    "KOMETA_RADARRTOKEN",
    "KOMETA_SONARRURL",
    "KOMETA_SONARRTOKEN",
    "KOMETA_GOTIFYURL",
    "KOMETA_GOTIFYTOKEN",
]


def log_header():
    """Print a startup banner matching Kometa's log style."""
    total_mem, avail_mem = _get_memory_gb()
    priority = _get_priority()
    log.info("=")
    log.info("")
    log.info("    Last Chance Cleanup Script")
    log.info("    Version: %s (Python %s)", VERSION, platform.python_version())
    log.info("    Platform: %s", platform.platform())
    if total_mem is not None:
        log.info("    Total Memory: %d GB", total_mem)
        log.info("    Available Memory: %d GB", avail_mem)
    log.info("    Process Priority: %s", priority)
    log.info("")


def log_run_details(args):
    """Log run command, flags, and secrets (DEBUG level — file only)."""
    log.debug("=")
    cmd_parts = ["lastchance.py"]
    for attr, flag in _ARG_ENV_MAP:
        val = getattr(args, attr, None)
        if val is True:
            cmd_parts.append(flag)
        elif val:
            cmd_parts.extend([flag, val])
    log.debug("Run Command: %s", " ".join(cmd_parts))

    # Log each flag and its value
    for attr, flag in _ARG_ENV_MAP:
        val = getattr(args, attr, None)
        if isinstance(val, bool):
            log.debug("%s: %s", flag, val)
        else:
            log.debug("%s: %s", flag, f'"{val}"' if val else "(default)")
    log.debug("")

    # Log secrets
    log.debug("Last Chance Secrets Read:")
    for env_var in _SECRET_ENV_VARS:
        val = os.environ.get(env_var)
        status = "(redacted)" if val else "(not set)"
        flag = f"--{env_var.lower().replace('_', '-')}"
        log.debug("%s (%s): %s", flag, env_var, status)
    log.debug("")


def log_start_banner():
    """Log a centered 'Starting Cleanup Run' banner."""
    log.info("=")
    log.info("Starting Cleanup Run", extra={"center": True})
    log.info("=")


def load_env_file(path):
    """Load KEY=VALUE pairs from a file into os.environ."""
    env_path = Path(path)
    if not env_path.is_file():
        log.error("Env file not found: %s", path)
        sys.exit(1)
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def get_env(name, required=True):
    val = os.environ.get(name)
    if required and not val:
        log.error("Missing required environment variable: %s", name)
        sys.exit(1)
    return val


def extract_id(guids, provider):
    """Extract a numeric ID from Plex GUID list for a given provider (tmdb, tvdb)."""
    prefix = f"{provider}://"
    for guid in guids:
        guid_id = guid.id if hasattr(guid, "id") else str(guid)
        if guid_id.startswith(prefix):
            try:
                return int(guid_id.split("://", 1)[1])
            except ValueError:
                continue
    return None


def fetch_arr_catalog(url, token, endpoint, id_key):
    """Fetch all items from a *arr instance, keyed by external ID."""
    resp = requests.get(
        f"{url}/api/v3/{endpoint}",
        headers={"X-Api-Key": token},
        timeout=30,
    )
    resp.raise_for_status()
    return {item[id_key]: item for item in resp.json()}


def delete_from_arr(cfg, arr_id, title, delete_files, import_exclude, dry_run):
    """Delete an item from Radarr or Sonarr."""
    if dry_run:
        log.info("  [DRY RUN] Would delete from %s: %s", cfg["label"], title)
        return True
    try:
        resp = requests.delete(
            f"{cfg['url']}/api/v3/{cfg['endpoint']}/{arr_id}",
            headers={"X-Api-Key": cfg["token"]},
            params={
                "deleteFiles": str(delete_files).lower(),
                "addImportExclusion": str(import_exclude).lower(),
            },
            timeout=30,
        )
        resp.raise_for_status()
        log.info("  Deleted from %s: %s", cfg["label"], title)
        return True
    except requests.RequestException as e:
        log.warning("  Failed to delete from %s: %s — %s", cfg["label"], title, e)
        return False


def delete_from_plex(item, dry_run):
    """Delete an item from Plex."""
    if dry_run:
        log.info("  [DRY RUN] Would delete from Plex: %s", item.title)
        return True
    try:
        item.delete()
        log.info("  Deleted from Plex: %s", item.title)
        return True
    except Exception as e:
        log.warning("  Failed to delete from Plex: %s — %s", item.title, e)
        return False


def send_gotify(url, token, deleted, failed, dry_run):
    """Send a Gotify notification summarizing deletions."""
    if not url or not token:
        return

    prefix = "[DRY RUN] " if dry_run else ""
    title = f"{prefix}Last Chance Cleanup — {datetime.now().strftime('%B %Y')}"

    # Build markdown message for Gotify
    lines = []
    if deleted:
        lines.append(f"**{prefix}Removed {len(deleted)} item(s):**")
        lines.extend(f"- {i}" for i in deleted)
    else:
        lines.append("No items to remove.")
    if failed:
        lines.append(f"\n**Failed to remove {len(failed)} item(s):**")
        lines.extend(f"- {i}" for i in failed)
    message = "\n".join(lines)

    # Log notification content (clean, no markdown)
    log.info("Title: %s", title)
    if deleted:
        log.info("Removed %d item(s):", len(deleted))
        for item in deleted:
            log.info("  %s", item)
    else:
        log.info("No items to remove.")
    if failed:
        log.info("Failed to remove %d item(s):", len(failed))
        for item in failed:
            log.info("  %s", item)

    if dry_run:
        log.info("")
        log.info("[DRY RUN] Notification not sent")
        return

    try:
        requests.post(
            f"{url}/message",
            headers={"X-Gotify-Key": token},
            json={
                "title": title,
                "message": message,
                "priority": 5,
                "extras": {"client::display": {"contentType": "text/markdown"}},
            },
            timeout=15,
        ).raise_for_status()
        log.info("")
        log.info("Notification sent successfully")
    except requests.RequestException as e:
        log.warning("Failed to send Gotify notification: %s", e)


def main():
    parser = argparse.ArgumentParser(description="Last Chance collection cleanup")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview deletions without executing"
    )
    parser.add_argument(
        "--env-file", metavar="PATH", help="Load environment variables from file"
    )
    parser.add_argument(
        "--no-notify", action="store_true", help="Skip Gotify notification"
    )
    parser.add_argument(
        "--no-delete-files",
        action="store_true",
        help="Remove from *arr but keep files on disk",
    )
    parser.add_argument(
        "--import-exclude", action="store_true", help="Add import exclusion in *arr"
    )
    args = parser.parse_args()

    log_header()

    if not args.env_file and DEFAULT_ENV.is_file():
        load_env_file(str(DEFAULT_ENV))
    elif args.env_file:
        load_env_file(args.env_file)

    log_run_details(args)
    log_start_banner()

    if args.dry_run:
        log.info("=== DRY RUN MODE — no changes will be made ===")

    # Config — uses same KOMETA_ prefix as Kometa (<<PLEXURL>> -> KOMETA_PLEXURL, etc.)
    plex_url = get_env("KOMETA_PLEXURL")
    plex_token = get_env("KOMETA_PLEXTOKEN")
    gotify_url = get_env("KOMETA_GOTIFYURL", required=False)
    gotify_token = get_env("KOMETA_GOTIFYTOKEN", required=False)
    delete_files = not args.no_delete_files
    import_exclude = args.import_exclude

    _secrets.extend(v for v in [plex_token, gotify_token] if v)

    # Connect to Plex
    log.info("=")
    log.info("Connecting to Plex...")
    plex = PlexServer(plex_url, plex_token)
    log.info("Plex Connection Successful")

    # Fetch *arr catalogs
    for cfg in ARR_CONFIG.values():
        cfg["url"] = get_env(cfg["url_env"])
        cfg["token"] = get_env(cfg["token_env"])
        if cfg["token"]:
            _secrets.append(cfg["token"])
        log.info("=")
        log.info("Connecting to %s...", cfg["label"])
        cfg["catalog"] = fetch_arr_catalog(
            cfg["url"], cfg["token"], cfg["endpoint"], cfg["key"]
        )
        log.info(
            "%s Connection Successful (%d items)", cfg["label"], len(cfg["catalog"])
        )

    # Gotify connection check
    log.info("=")
    if gotify_url and gotify_token:
        log.info("Connecting to Gotify...")
        log.info("Gotify Connection Successful")
    else:
        log.info("Gotify not configured, skipping notifications")
    log.info("=")

    deleted_items = []
    failed_items = []
    arr_deleted_ids = set()  # Track *arr IDs already deleted across libraries
    library_results = []  # Per-library stats for summary
    start_time = datetime.now()

    for section in plex.library.sections():
        if section.type not in ARR_CONFIG:
            continue

        lib_start = datetime.now()
        lib_deleted = 0
        lib_failed = 0

        # Find collection
        try:
            collection = next(
                (
                    c
                    for c in section.collections(title=COLLECTION_NAME)
                    if c.title == COLLECTION_NAME
                ),
                None,
            )
        except Exception:
            collection = None

        # Library header (matches Kometa format)
        log.info("")
        log.info("=")
        log.info("%s Library", section.title, extra={"center": True})
        log.info("=")

        if not collection:
            log.info("")
            log.info("No '%s' collection, skipping", COLLECTION_NAME)
            library_results.append((section.title, 0, 0, datetime.now() - lib_start))
            continue

        items = collection.items()
        if not items:
            log.info("")
            log.info("Collection empty, skipping")
            library_results.append((section.title, 0, 0, datetime.now() - lib_start))
            continue

        cfg = ARR_CONFIG[section.type]
        label = f"[{section.title}]"
        log.info("")
        log.info("%s %d item(s) in '%s' collection", label, len(items), COLLECTION_NAME)

        for item in items:
            title = (
                f"{item.title} ({item.year})"
                if getattr(item, "year", None)
                else item.title
            )
            log.info("")
            log.info("  %s", title)

            # Delete from Radarr/Sonarr
            arr_deleted = False
            ext_id = extract_id(item.guids, cfg["provider"])
            arr_key = (cfg["endpoint"], ext_id)
            if ext_id and ext_id in cfg["catalog"] and arr_key not in arr_deleted_ids:
                arr_deleted = delete_from_arr(
                    cfg,
                    cfg["catalog"][ext_id]["id"],
                    title,
                    delete_files,
                    import_exclude,
                    args.dry_run,
                )
                if arr_deleted:
                    arr_deleted_ids.add(arr_key)
            elif ext_id and arr_key in arr_deleted_ids:
                log.info("    Already deleted from %s, skipping", cfg["label"])
                arr_deleted = True
            elif ext_id:
                log.warning(
                    "    %s ID %s not found in %s",
                    cfg["provider"].upper(),
                    ext_id,
                    cfg["label"],
                )
            else:
                log.warning("    No %s ID for %s", cfg["provider"].upper(), title)

            # Delete from Plex
            plex_deleted = delete_from_plex(item, args.dry_run)

            if plex_deleted or arr_deleted:
                deleted_items.append(f"{label} {title}")
                lib_deleted += 1
            else:
                failed_items.append(f"{label} {title}")
                lib_failed += 1

        library_results.append(
            (section.title, lib_deleted, lib_failed, datetime.now() - lib_start)
        )
        log.info("")
        log.info("=")

    # Send notification before summary
    if not args.no_notify and gotify_url and gotify_token:
        log.info("")
        log.info("=")
        log.info("Sending Notification", extra={"center": True})
        log.info("=")
        log.info("")
        send_gotify(gotify_url, gotify_token, deleted_items, failed_items, args.dry_run)

    # Summary
    end_time = datetime.now()
    run_time = end_time - start_time
    extra = {"center": True}

    log.info("")
    log.info("=")
    log.info("Summary", extra=extra)
    log.info("=")
    log.info("")

    if library_results:
        # Library table
        name_w = max(len(r[0]) for r in library_results)
        name_w = max(name_w, 7)  # min width for "Library"
        log.info(" %-*s | Deleted | Failed | Run Time ", name_w, "Library")
        log.info(" %s | ======= | ====== | ========", "=" * name_w)
        for name, d, f, rt in library_results:
            log.info(
                " %-*s | %7d | %6d | %s", name_w, name, d, f, str(rt).split(".")[0]
            )
        log.info("")

    if failed_items:
        log.info("=" * 20 + " Error Summary " + "=" * 20)
        log.info("")
        for item in failed_items:
            log.info(" Failed: %s", item)
        log.info("")

    log.info("=")
    log.info("Finished Cleanup Run", extra=extra)
    log.info("Version: %s", VERSION, extra=extra)
    start_fmt = start_time.strftime("%H:%M:%S %Y-%m-%d")
    end_fmt = end_time.strftime("%H:%M:%S %Y-%m-%d")
    rt_str = str(run_time).split(".")[0]
    log.info(
        "Start Time: %s     Finished: %s     Run Time: %s",
        start_fmt,
        end_fmt,
        rt_str,
        extra=extra,
    )
    log.info("=")


if __name__ == "__main__":
    main()
