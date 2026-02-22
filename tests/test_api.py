#!/usr/bin/env python3
"""
Test script for Pi API client.
Tests communication with Save4223 backend (or mock server).
"""

import sys
import time
import uuid
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from api_client import APIClient, APIError
from local_db import LocalDB
from sync_worker import SyncWorker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
# Use localhost:3001 for mock server, or 100.83.123.68:3000 for real server
SERVER_URL = "http://localhost:3001"  # Change to mock server port
EDGE_SECRET = "edge_device_secret_key"
CABINET_ID = 1


def test_health_check():
    """Test 1: Health check."""
    logger.info("\n" + "="*50)
    logger.info("TEST 1: Health Check")
    logger.info("="*50)
    
    api = APIClient(SERVER_URL, EDGE_SECRET)
    
    try:
        is_healthy = api.health_check()
        if is_healthy:
            logger.info("✅ Server is online")
        else:
            logger.error("❌ Server health check failed")
        return is_healthy
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return False


def test_authorize():
    """Test 2: Card authorization."""
    logger.info("\n" + "="*50)
    logger.info("TEST 2: Card Authorization")
    logger.info("="*50)
    
    api = APIClient(SERVER_URL, EDGE_SECRET)
    
    # Test with valid card
    try:
        logger.info("Testing valid card (TEST123)...")
        result = api.authorize("TEST123", CABINET_ID)
        logger.info(f"✅ Auth result: {result}")
        assert result['authorized'] == True
        assert 'session_id' in result
        assert 'user_id' in result
    except Exception as e:
        logger.error(f"❌ Valid card test failed: {e}")
        return False
    
    # Test with invalid card
    try:
        logger.info("\nTesting invalid card (INVALID)...")
        result = api.authorize("INVALID", CABINET_ID)
        logger.error(f"❌ Should have failed but got: {result}")
        return False
    except APIError as e:
        logger.info(f"✅ Correctly rejected invalid card: {e}")
    
    return True


def test_sync_session():
    """Test 3: Session sync."""
    logger.info("\n" + "="*50)
    logger.info("TEST 3: Session Sync")
    logger.info("="*50)
    
    api = APIClient(SERVER_URL, EDGE_SECRET)
    
    session_id = str(uuid.uuid4())
    user_id = "550e8400-e29b-41d4-a716-446655440001"
    
    # Simulate user taking Oscilloscope #2 and returning Multimeter #1
    # RFID-OSC-002 is present (was available, now taken)
    # RFID-MUL-001 is NOT present (was borrowed, now returned)
    rfids_present = [
        "RFID-OSC-001",  # Still borrowed by someone else
        "RFID-OSC-003",  # Available
        # RFID-OSC-002 is gone (borrowed)
        "RFID-TOOL-001", # Available
        # RFID-MUL-001 is returned (now present)
        "RFID-MUL-002",  # Available
    ]
    
    try:
        result = api.sync_session(session_id, CABINET_ID, user_id, rfids_present)
        logger.info(f"✅ Sync result: {result}")
        
        logger.info(f"\n📤 Borrowed ({len(result['borrowed'])}):")
        for item in result['borrowed']:
            logger.info(f"   - {item['name']} ({item['rfid']})")
        
        logger.info(f"\n📥 Returned ({len(result['returned'])}):")
        for item in result['returned']:
            logger.info(f"   - {item['name']} ({item['rfid']})")
        
        return True
    except Exception as e:
        logger.error(f"❌ Sync failed: {e}")
        return False


def test_local_sync():
    """Test 4: Local sync data."""
    logger.info("\n" + "="*50)
    logger.info("TEST 4: Local Sync Data")
    logger.info("="*50)
    
    api = APIClient(SERVER_URL, EDGE_SECRET)
    
    try:
        result = api.local_sync(CABINET_ID)
        logger.info(f"✅ Local sync data received")
        logger.info(f"   Cards: {len(result['cards'])}")
        logger.info(f"   Items: {len(result['items'])}")
        
        for card in result['cards']:
            logger.info(f"   - Card: {card['card_uid']} -> User: {card['user_id'][:8]}...")
        
        return True
    except Exception as e:
        logger.error(f"❌ Local sync failed: {e}")
        return False


def test_local_db():
    """Test 5: Local database operations."""
    logger.info("\n" + "="*50)
    logger.info("TEST 5: Local Database")
    logger.info("="*50)
    
    import tempfile
    import os
    
    # Use temp database for testing
    db_path = tempfile.mktemp(suffix='.db')
    
    try:
        db = LocalDB(db_path)
        logger.info(f"✅ Database created at {db_path}")
        
        # Test cache auth
        auth_result = {
            'authorized': True,
            'user_id': 'test-user-123',
            'user_name': 'Test User',
            'cabinet_id': 1
        }
        db.cache_auth('TEST-CARD', auth_result, ttl=3600)
        logger.info("✅ Auth cached")
        
        # Test retrieve cached auth
        cached = db.get_cached_auth('TEST-CARD')
        if cached:
            logger.info(f"✅ Auth retrieved from cache: {cached}")
        else:
            logger.error("❌ Failed to retrieve cached auth")
            return False
        
        # Test queue sync
        db.queue_sync_session('session-123', 'user-123', ['RFID-001', 'RFID-002'])
        logger.info("✅ Sync session queued")
        
        # Test get pending
        pending = db.get_pending_sync()
        logger.info(f"✅ Pending sync items: {len(pending)}")
        
        # Test log access
        db.log_access('TEST-CARD', 'user-123', 'session-123', ['RFID-001'])
        logger.info("✅ Access logged")
        
        db.close()
        logger.info("✅ Database closed")
        
        # Cleanup
        os.remove(db_path)
        
        return True
    except Exception as e:
        logger.error(f"❌ Database test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_sync_worker():
    """Test 6: Sync worker (brief test)."""
    logger.info("\n" + "="*50)
    logger.info("TEST 6: Sync Worker")
    logger.info("="*50)
    
    import tempfile
    db_path = tempfile.mktemp(suffix='.db')
    
    try:
        db = LocalDB(db_path)
        api = APIClient(SERVER_URL, EDGE_SECRET)
        
        # Create worker with short interval for testing
        worker = SyncWorker(db, api, interval=2)
        
        logger.info("Starting sync worker...")
        worker.start()
        
        # Queue some test data
        db.queue_sync_session('test-session-1', 'user-1', ['RFID-001'])
        db.queue_sync_session('test-session-2', 'user-2', ['RFID-002', 'RFID-003'])
        logger.info("✅ Test sync data queued")
        
        # Wait a bit for sync
        logger.info("Waiting 3 seconds for sync attempt...")
        time.sleep(3)
        
        # Check if online
        if worker.is_online():
            logger.info("✅ Worker is online")
            pending = db.get_pending_sync()
            logger.info(f"   Pending items after sync: {len(pending)}")
        else:
            logger.warning("⚠️ Worker is offline (mock server may not be running)")
        
        worker.stop()
        logger.info("✅ Worker stopped")
        
        db.close()
        import os
        os.remove(db_path)
        
        return True
    except Exception as e:
        logger.error(f"❌ Sync worker test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all tests."""
    logger.info("\n" + "🧪"*25)
    logger.info("SAVE4223 PI API CLIENT TEST SUITE")
    logger.info("🧪"*25)
    logger.info(f"Server: {SERVER_URL}")
    logger.info(f"Cabinet ID: {CABINET_ID}")
    
    tests = [
        ("Health Check", test_health_check),
        ("Authorization", test_authorize),
        ("Session Sync", test_sync_session),
        ("Local Sync", test_local_sync),
        ("Local Database", test_local_db),
        ("Sync Worker", test_sync_worker),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            logger.error(f"❌ Test '{name}' crashed: {e}")
            results.append((name, False))
    
    # Summary
    logger.info("\n" + "="*50)
    logger.info("TEST SUMMARY")
    logger.info("="*50)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status}: {name}")
    
    logger.info(f"\nTotal: {passed}/{total} tests passed")
    
    return passed == total


if __name__ == "__main__":
    # Allow overriding server URL via command line
    if len(sys.argv) > 1:
        SERVER_URL = sys.argv[1]
        logger.info(f"Using server: {SERVER_URL}")
    
    success = run_all_tests()
    sys.exit(0 if success else 1)
