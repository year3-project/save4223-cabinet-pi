#!/usr/bin/env python3
"""Full reset of local SQLite database and re-sync from remote server.

Wipes all local tables, then fetches fresh data from the remote Edge API
using GET /api/edge/local-sync.

Usage:
    uv run scripts/full_reset_local_db.py              # Interactive (prompts for confirmation)
    uv run scripts/full_reset_local_db.py --yes        # Skip confirmation prompt
    uv run scripts/full_reset_local_db.py --no-backup  # Skip database backup before reset

Auto-sudos if the database file is owned by root (written by the systemd service).
"""

import argparse
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config
from src.api_client import APIClient
from src.local_db import LocalDB


def get_table_counts(conn: sqlite3.Connection) -> dict:
    """Get row counts for all tables."""
    tables = [
        "auth_cache", "item_types", "item_cache",
        "rfid_snapshots", "session_diffs", "pending_sync",
        "pending_pairings", "borrow_history", "access_logs",
        "offline_queue",
    ]
    counts = {}
    for table in tables:
        try:
            row = conn.execute(f"SELECT COUNT(*) as count FROM {table}").fetchone()
            counts[table] = row[0]
        except sqlite3.OperationalError:
            counts[table] = 0
    return counts


def print_counts(label: str, counts: dict):
    """Print table counts in a readable format."""
    print(f"\n  {label}")
    print("  " + "-" * 40)
    total = 0
    for table, count in counts.items():
        print(f"    {table:<22} {count:>6} rows")
        total += count
    print(f"    {'TOTAL':<22} {total:>6} rows")


def reset_database(db_path: str, backup: bool = True) -> bool:
    """Delete all rows from all tables, vacuum, and recreate schema."""
    db_file = Path(db_path)

    if not db_file.exists():
        print(f"  Database not found at {db_path}, will create fresh.")
        return True

    # Backup
    if backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_file.parent / f"local.db.bak.{timestamp}"
        print(f"  Backing up to {backup_path}")
        shutil.copy2(db_file, backup_path)

    # Connect and wipe
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    tables = [
        "rfid_snapshots", "session_diffs", "pending_sync",
        "pending_pairings", "borrow_history", "access_logs",
        "offline_queue", "item_cache", "item_types", "auth_cache",
    ]

    for table in tables:
        try:
            conn.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError:
            pass  # Table may not exist yet

    conn.commit()

    # Vacuum to reclaim space
    print("  Vacuuming database...")
    conn.execute("VACUUM")
    conn.close()

    print("  Database wiped.")
    return True


def sync_from_remote(config: dict) -> bool:
    """Fetch fresh data from remote and populate local DB."""
    # Build API client
    api = APIClient(
        base_url=config["server_url"],
        edge_secret=config["edge_secret"],
        timeout=config.get("api", {}).get("timeout", 10),
        max_retries=config.get("api", {}).get("max_retries", 3),
        retry_delay=config.get("api", {}).get("retry_delay", 2.0),
        verify_ssl=config.get("ssl", {}).get("verify", True),
        cert_path=config.get("ssl", {}).get("cert_path"),
    )

    cabinet_id = config["cabinet_id"]

    # Health check first
    print(f"\n  Checking connection to {config['server_url']}...")
    if not api.health_check():
        print("  ERROR: Server is not reachable. Aborting.")
        return False
    print("  Server is online.")

    # Fetch sync data
    print(f"  Fetching data for cabinet {cabinet_id}...")
    result = api.local_sync(cabinet_id=cabinet_id)

    users = result.get("users", [])
    item_types = result.get("item_types", [])
    items = result.get("items", [])

    print(f"  Received: {len(users)} users, {len(item_types)} item types, {len(items)} items")

    if not users and not item_types and not items:
        print("  WARNING: No data returned from server. Check cabinet_id and edge_secret.")

    # Open fresh DB connection (schema auto-created by LocalDB.__init__)
    db = LocalDB(config["db_path"])

    # Populate item types
    for it in item_types:
        db.update_item_type(
            id=it["id"],
            name=it["name"],
            name_cn=it.get("name_cn"),
            category=it.get("category"),
            description=it.get("description"),
        )

    # Populate items
    for item in items:
        db.update_item_cache(
            rfid_tag=item["rfid_tag"],
            item_id=item["id"],
            name=item.get("item_type_name", "Unknown"),
            item_type_id=item.get("item_type_id"),
            item_type_name=item.get("item_type_name"),
            status=item.get("status", "AVAILABLE"),
            holder_id=item.get("holder_id"),
            location_id=item.get("location_id"),
        )

    # Populate auth cache
    for user in users:
        db.cache_auth(
            card_uid=user["card_uid"],
            auth_result={
                "user_id": user["user_id"],
                "user_name": user["user_name"],
                "email": user.get("email"),
                "role": user.get("role", "USER"),
            },
            ttl=3600 * 24,  # 24 hours
        )

    db.close()
    return True


def ensure_write_access(db_path: str):
    """Re-execute this script with sudo to get write access to the database.

    This function does not return — it either succeeds with sudo or exits.
    """
    print("  Database file is not writable (owned by root).")
    print("  Re-running with sudo...\n")

    import subprocess
    result = subprocess.run(
        ["sudo", sys.executable, *sys.argv],
        cwd=str(PROJECT_ROOT),
    )
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="Reset local DB and re-sync from remote")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--no-backup", action="store_true", help="Skip database backup")
    args = parser.parse_args()

    config = load_config()
    db_path = config["db_path"]

    # Resolve relative db_path against the project root
    db_path_resolved = (PROJECT_ROOT / db_path).resolve()
    config["db_path"] = str(db_path_resolved)

    print("=" * 50)
    print("  Save4223 Cabinet Pi — DB Reset & Refresh")
    print("=" * 50)
    print(f"\n  Database: {db_path_resolved}")

    # Ensure we can write to the db (auto-sudos if needed)
    if db_path_resolved.exists() and not os.access(db_path_resolved, os.W_OK):
        ensure_write_access(str(db_path_resolved))  # re-execs with sudo, won't return

    # Show current state
    if db_path_resolved.exists():
        conn = sqlite3.connect(str(db_path_resolved))
        counts = get_table_counts(conn)
        conn.close()
        print_counts("Current database state", counts)
    else:
        print("\n  No existing database found.")

    # Confirm
    if not args.yes:
        response = input("\n  This will DELETE ALL local data and re-fetch from remote. Continue? [y/N] ")
        if response.lower() not in ("y", "yes"):
            print("  Aborted.")
            return

    # Reset
    print("\n  [1/2] Resetting database...")
    t0 = time.time()
    reset_database(str(db_path_resolved), backup=not args.no_backup)
    print(f"  Done in {time.time() - t0:.1f}s")

    # Sync
    print("\n  [2/2] Syncing from remote...")
    t0 = time.time()
    ok = sync_from_remote(config)
    print(f"  Done in {time.time() - t0:.1f}s")

    if not ok:
        print("\n  Sync failed. The database has been wiped but not re-populated.")
        print("  Re-run this script or restart the cabinet service to retry.")
        sys.exit(1)

    # Show new state
    conn = sqlite3.connect(str(db_path_resolved))
    counts = get_table_counts(conn)
    conn.close()
    print_counts("New database state", counts)

    print("\n  Reset complete.\n")


if __name__ == "__main__":
    main()
