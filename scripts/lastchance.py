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
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests
from plexapi.server import PlexServer

COLLECTION_NAME = "Last Chance"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = "lastchance.log"
LOG_BACKUPS = 9

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


def setup_logging():
    """Configure logging to match Kometa's log pattern — file + console."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / LOG_FILE

    log = logging.getLogger("lastchance")
    log.setLevel(logging.INFO)
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
        mode="a",
        backupCount=LOG_BACKUPS,
        encoding="utf-8",
    )
    file_handler.namer = log_namer
    if log_path.exists() and log_path.stat().st_size > 0:
        file_handler.doRollover()
    file_handler.setFormatter(
        logging.Formatter(
            fmt="[%(asctime)s] %(levelname)-10s | %(message)s |",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    log.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter(
            fmt="| %(message)s |",
        )
    )
    log.addHandler(console_handler)

    return log


log = setup_logging()


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
    log.info("Loaded environment from %s", path)


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

    if dry_run:
        log.info("[DRY RUN] Gotify notification:\n%s", message)
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
        log.info("Gotify notification sent")
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

    if args.env_file:
        load_env_file(args.env_file)

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

    # Connect to Plex and fetch *arr catalogs
    log.info("Connecting to Plex...")
    plex = PlexServer(plex_url, plex_token)

    for cfg in ARR_CONFIG.values():
        cfg["url"] = get_env(cfg["url_env"])
        cfg["token"] = get_env(cfg["token_env"])
        if cfg["token"]:
            _secrets.append(cfg["token"])
        log.info("Fetching %s catalog...", cfg["label"])
        cfg["catalog"] = fetch_arr_catalog(
            cfg["url"], cfg["token"], cfg["endpoint"], cfg["key"]
        )
        log.info("  Found %d items in %s", len(cfg["catalog"]), cfg["label"])

    deleted_items = []
    failed_items = []
    arr_deleted_ids = set()  # Track *arr IDs already deleted across libraries

    for section in plex.library.sections():
        if section.type not in ARR_CONFIG:
            continue

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

        if not collection:
            log.info(
                "[%s] No '%s' collection, skipping", section.title, COLLECTION_NAME
            )
            continue

        items = collection.items()
        if not items:
            log.info("[%s] Collection empty, skipping", section.title)
            continue

        cfg = ARR_CONFIG[section.type]
        label = f"[{section.title}]"
        log.info("%s Processing %d item(s)", label, len(items))

        for item in items:
            title = (
                f"{item.title} ({item.year})"
                if getattr(item, "year", None)
                else item.title
            )
            log.info("  %s %s", label, title)

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

            (deleted_items if plex_deleted or arr_deleted else failed_items).append(
                f"{label} {title}"
            )

    log.info("=" * 50)
    log.info(
        "Cleanup complete: %d deleted, %d failed", len(deleted_items), len(failed_items)
    )
    if not args.no_notify:
        send_gotify(gotify_url, gotify_token, deleted_items, failed_items, args.dry_run)


if __name__ == "__main__":
    main()
