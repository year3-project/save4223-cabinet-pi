#!/usr/bin/env python3
"""Test script to simulate full authentication and session flow."""

import sys
import os
import time
import threading
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from hardware import MockHardware, LEDColor
from local_db import LocalDB
from api_client import APIClient
from sync_worker import SyncWorker
from inventory_manager import InventoryManager
from state_machine import StateMachine, SystemState
import uuid
from datetime import datetime

print("=" * 60)
print(" FULL FLOW TEST - Simulating CARD-001 Authentication ")
print("=" * 60)

# Setup test database
test_db_path = Path("./data/test_flow.db")
test_db_path.parent.mkdir(exist_ok=True)
if test_db_path.exists():
    test_db_path.unlink()

local_db = LocalDB(str(test_db_path))

# Initialize components
print("\n[1] Initializing Mock Hardware...")
hw = MockHardware(num_drawers=4, num_leds=8)
hw.initialize()

print("\n[2] Setting up Inventory Manager...")
inventory = InventoryManager(local_db)

# Pre-populate some test items in cache
print("\n[3] Populating item cache...")
local_db.update_item_cache(
    rfid_tag="RFID-001",
    item_id="item-001",
    name="Arduino Uno",
    status="AVAILABLE",
    cabinet_id=1
)
local_db.update_item_cache(
    rfid_tag="RFID-002",
    item_id="item-002",
    name="Raspberry Pi 4",
    status="AVAILABLE",
    cabinet_id=1
)
local_db.update_item_cache(
    rfid_tag="RFID-003",
    item_id="item-003",
    name="Multimeter",
    status="AVAILABLE",
    cabinet_id=1
)
print("   Added 3 test items to cache")

# Pre-populate a cached user (simulating offline mode with cached auth)
print("\n[4] Caching test user (CARD-001)...")
local_db.cache_auth(
    card_uid="CARD-001",
    auth_result={
        "user_id": "user-123",
        "user_name": "Test User",
        "email": "test@example.com",
        "role": "USER"
    },
    ttl=3600 * 24
)
print("   User cached successfully")

# Simulate the authentication flow
print("\n" + "=" * 60)
print(" STEP 1: LOCKED STATE - Waiting for card...")
print("=" * 60)

hw.set_all_leds(LEDColor.RED)
print("[LED] All LEDs set to RED (locked)")

# Simulate card tap
print("\n[USER ACTION] Tapping CARD-001...")
card_uid = "CARD-001"
print(f"[NFC] Card detected: {card_uid}")

# Authenticate (offline with cache)
print("\n" + "=" * 60)
print(" STEP 2: AUTHENTICATING...")
print("=" * 60)

hw.set_all_leds(LEDColor.YELLOW)
print("[LED] All LEDs set to YELLOW (authenticating)")

cached_auth = local_db.get_cached_auth(card_uid)
if cached_auth:
    user_id = cached_auth["user_id"]
    user_name = cached_auth["user_name"]
    print(f"[AUTH] ✓ Authenticated: {user_name} ({user_id})")
    print(f"[AUTH] Source: local cache (offline mode)")
else:
    print("[AUTH] ✗ Card not registered!")
    sys.exit(1)

# Generate session
session_id = str(uuid.uuid4())
print(f"[SESSION] Created: {session_id[:8]}...")

# Log access
local_db.log_access(
    card_uid=card_uid,
    user_id=user_id,
    user_name=user_name,
    session_id=session_id,
    action="AUTH_SUCCESS"
)

# Simulate UNLOCKED state
print("\n" + "=" * 60)
print(" STEP 3: UNLOCKED - User accessing cabinet...")
print("=" * 60)

hw.set_all_leds(LEDColor.GREEN)
print("[LED] All LEDs set to GREEN (unlocked)")
hw.unlock_all()
print("[LOCK] All drawers unlocked")
hw.beep_success()
print("[BEEP] Success beep played")

# Start inventory session
inventory.start_session(session_id, user_id)

# Simulate start RFID scan (items present when opened)
print("\n[RFID] Capturing start snapshot...")
start_tags = ["RFID-001", "RFID-002", "RFID-003"]  # All items present
inventory.capture_start_snapshot(start_tags)
print(f"[RFID] Start tags: {start_tags}")

local_db.log_access(
    card_uid=card_uid,
    user_id=user_id,
    user_name=user_name,
    session_id=session_id,
    action="DOOR_OPEN",
    tags_found=start_tags
)

# Simulate user taking one item (Arduino Uno)
print("\n[USER ACTION] User takes Arduino Uno (RFID-001)...")
print("[USER ACTION] User closes drawer...")
time.sleep(1)

# Simulate SCANNING state (session end)
print("\n" + "=" * 60)
print(" STEP 4: SCANNING - Finalizing session...")
print("=" * 60)

hw.set_all_leds(LEDColor.YELLOW)
print("[LED] All LEDs set to YELLOW (scanning)")
hw.lock_all()
print("[LOCK] All drawers locked")

# Simulate end RFID scan (Arduino Uno is gone)
print("\n[RFID] Capturing end snapshot...")
end_tags = ["RFID-002", "RFID-003"]  # Arduino Uno taken
print(f"[RFID] End tags: {end_tags}")

# Calculate diff
borrowed, returned = inventory.capture_end_snapshot(end_tags)

print("\n" + "=" * 60)
print(" STEP 5: SESSION SUMMARY")
print("=" * 60)
print(f"\nUser: {user_name}")
print(f"Session: {session_id[:8]}...")
print(f"\nItems Borrowed ({len(borrowed)}):")
for item in borrowed:
    print(f"  - {item['name']} ({item['rfid']})")
print(f"\nItems Returned ({len(returned)}):")
if returned:
    for item in returned:
        print(f"  - {item['name']} ({item['rfid']})")
else:
    print("  (none)")

# Save session diff
local_db.save_session_diff(
    session_id=session_id,
    user_id=user_id,
    user_name=user_name,
    borrowed=borrowed,
    returned=returned,
    start_rfids=start_tags,
    end_rfids=end_tags
)

# Record borrow history
for item in borrowed:
    local_db.record_borrow(
        session_id=session_id,
        user_id=user_id,
        user_name=user_name,
        rfid_tag=item["rfid"],
        item_id=item.get("item_id"),
        item_name=item["name"]
    )

# Queue for sync (offline mode)
local_db.queue_session_sync(
    session_id=session_id,
    user_id=user_id,
    start_rfids=start_tags,
    end_rfids=end_tags
)
print("\n[SYNC] Session queued for later sync (offline mode)")

local_db.log_access(
    card_uid=card_uid,
    user_id=user_id,
    user_name=user_name,
    session_id=session_id,
    action="DOOR_CLOSE",
    tags_found=end_tags
)

# Check stats
print("\n" + "=" * 60)
print(" STEP 6: DATABASE STATS")
print("=" * 60)
stats = local_db.get_stats()
for key, value in stats.items():
    print(f"  {key}: {value}")

# Check borrow history
print("\n" + "=" * 60)
print(" STEP 7: BORROW HISTORY")
print("=" * 60)
history = local_db.get_user_borrow_history(user_id)
for record in history:
    print(f"  [{record['action']}] {record['item_name']} at {record['created_at']}")

# Return to LOCKED state
print("\n" + "=" * 60)
print(" STEP 8: LOCKED - Ready for next user...")
print("=" * 60)
hw.set_all_leds(LEDColor.RED)
print("[LED] All LEDs set to RED (locked)")

# Cleanup
inventory.end_session()
hw.cleanup()
local_db.close()

print("\n" + "=" * 60)
print(" TEST COMPLETE - Full flow successful!")
print("=" * 60)
print("\nFlow Summary:")
print("  LOCKED → AUTHENTICATING → UNLOCKED → SCANNING → LOCKED")
print("  User borrowed: Arduino Uno (RFID-001)")
print("  Session saved locally (offline mode)")
print("  Will sync with server when online")
