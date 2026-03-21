#!/usr/bin/env python3
"""API testing script for Save4223 Edge API."""

import requests
import json
import sys
from uuid import uuid4

# Configuration
BASE_URL = "https://lovelace.tail20b481.ts.net:3001"
EDGE_SECRET = "edge_device_secret_key"
CABINET_ID = 7  # Must match existing location in database

# SSL verification (False for local testing with self-signed cert)
VERIFY_SSL = False

if not VERIFY_SSL:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "Authorization": f"Bearer {EDGE_SECRET}",
    "Content-Type": "application/json"
}


def test_health():
    """Test server health."""
    print("\n" + "="*50)
    print("TEST: Server Health Check")
    print("="*50)

    try:
        r = requests.get(f"{BASE_URL}/api/health", verify=VERIFY_SSL)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            print(f"Response: {r.json()}")
            return True
        else:
            print(f"Note: /api/health returned {r.status_code}")
            print(f"Trying main page instead...")
            r2 = requests.get(f"{BASE_URL}/", verify=VERIFY_SSL)
            print(f"Main page status: {r2.status_code}")
            return r2.status_code == 200
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_edge_health():
    """Test edge health with auth."""
    print("\n" + "="*50)
    print("TEST: Edge Health Check")
    print("="*50)

    try:
        r = requests.get(f"{BASE_URL}/api/edge/health",
                        headers=HEADERS, verify=VERIFY_SSL)
        print(f"Status: {r.status_code}")
        print(f"Response: {json.dumps(r.json(), indent=2)}")
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_authorize():
    """Test card authorization."""
    print("\n" + "="*50)
    print("TEST: Card Authorization")
    print("="*50)

    # Test 1: Unknown card (should return 403 with reason)
    payload = {
        "card_uid": "UNKNOWN-CARD",
        "cabinet_id": CABINET_ID
    }

    try:
        r = requests.post(f"{BASE_URL}/api/edge/authorize",
                         headers=HEADERS, json=payload, verify=VERIFY_SSL)
        print(f"Unknown card test:")
        print(f"  Status: {r.status_code}")
        print(f"  Response: {json.dumps(r.json(), indent=2)}")

        if r.status_code == 403 and "not registered" in r.json().get("reason", "").lower():
            print("  ✅ Correctly rejected unknown card")
            return True
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_sync_session():
    """Test session sync."""
    print("\n" + "="*50)
    print("TEST: Session Sync")
    print("="*50)

    session_id = str(uuid4())
    payload = {
        "session_id": session_id,
        "cabinet_id": CABINET_ID,
        "user_id": "550e8400-e29b-41d4-a716-446655440000",  # Valid UUID
        "start_rfids": ["RFID-001", "RFID-002", "RFID-003"],
        "end_rfids": ["RFID-002", "RFID-003"]  # RFID-001 borrowed
    }

    try:
        r = requests.post(f"{BASE_URL}/api/edge/sync-session",
                         headers=HEADERS, json=payload, verify=VERIFY_SSL)
        print(f"Status: {r.status_code}")
        response_data = r.json()
        print(f"Response: {json.dumps(response_data, indent=2)}")

        if r.status_code == 200:
            data = r.json()
            print(f"\n✅ Session synced:")
            print(f"   Borrowed: {data.get('summary', {}).get('borrowed', 0)}")
            print(f"   Returned: {data.get('summary', {}).get('returned', 0)}")
            return True
        elif r.status_code == 500:
            # Database might have missing tables - check error
            if "cabinet_sessions" in response_data.get("details", ""):
                print("\n⚠️  Database table 'cabinet_sessions' issue - needs schema check")
                return False
            return False
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_local_sync():
    """Test local sync (get cache data)."""
    print("\n" + "="*50)
    print("TEST: Local Sync (Cache Data)")
    print("="*50)

    try:
        r = requests.get(f"{BASE_URL}/api/edge/local-sync?cabinet_id={CABINET_ID}",
                        headers=HEADERS, verify=VERIFY_SSL)
        print(f"Status: {r.status_code}")
        data = r.json()
        print(f"Users: {len(data.get('users', []))}")
        print(f"Restricted cabinets: {data.get('restricted_cabinets', [])}")
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_sync_with_return():
    """Test session with return."""
    print("\n" + "="*50)
    print("TEST: Session with Return")
    print("="*50)

    session_id = str(uuid4())
    payload = {
        "session_id": session_id,
        "cabinet_id": CABINET_ID,
        "user_id": "550e8400-e29b-41d4-a716-446655440000",  # Valid UUID
        "start_rfids": ["RFID-002", "RFID-003"],  # Arduino not there
        "end_rfids": ["RFID-001", "RFID-002", "RFID-003"]  # Arduino returned
    }

    try:
        r = requests.post(f"{BASE_URL}/api/edge/sync-session",
                         headers=HEADERS, json=payload, verify=VERIFY_SSL)
        print(f"Status: {r.status_code}")
        data = r.json()
        print(f"Response: {json.dumps(data, indent=2)}")

        if r.status_code == 200:
            print(f"\n✅ Return detected:")
            for tx in data.get('transactions', []):
                if tx.get('action') == 'RETURN':
                    print(f"   Returned: {tx.get('rfid_tag')}")
            return True
        elif r.status_code == 500:
            if "cabinet_sessions" in data.get("details", ""):
                print("\n⚠️  Database issue - skipping return test")
            return False
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "="*50)
    print("Save4223 Edge API Test Suite")
    print(f"Base URL: {BASE_URL}")
    print("="*50)

    tests = [
        ("Health Check", test_health),
        ("Edge Health", test_edge_health),
        ("Authorize", test_authorize),
        ("Sync Session", test_sync_session),
        ("Local Sync", test_local_sync),
        ("Sync with Return", test_sync_with_return),
    ]

    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"\n❌ Test '{name}' failed: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "="*50)
    print("TEST SUMMARY")
    print("="*50)
    passed = sum(1 for _, r in results if r)
    total = len(results)
    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {status}: {name}")
    print(f"\nTotal: {passed}/{total} passed")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
