#!/usr/bin/env python3
"""Quick connection test for Save4223 Pi to Server."""

import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from api_client import APIClient, APIError

def test_connection():
    """Test connection to server."""

    # Load config
    config_path = Path(__file__).parent / "config.json"
    if not config_path.exists():
        print("❌ config.json not found! Copy from config.example.json")
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    print("=" * 50)
    print("Save4223 Pi Connection Test")
    print("=" * 50)
    print(f"Server URL: {config['server_url']}")
    print(f"Cabinet ID: {config['cabinet_id']}")
    print()

    # SSL configuration
    ssl_verify = config.get('ssl', {}).get('verify', False)
    cert_path = config.get('ssl', {}).get('cert_path')

    if not ssl_verify:
        print("⚠️  SSL verification disabled (dev mode)")
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Create API client
    api = APIClient(
        base_url=config['server_url'],
        edge_secret=config['edge_secret'],
        timeout=config.get('api', {}).get('timeout', 10),
        verify_ssl=ssl_verify,
        cert_path=cert_path if ssl_verify else None,
        max_retries=1,
        retry_delay=1.0
    )

    # Test 1: Basic health check
    print("\n1. Testing basic health check...")
    try:
        if api.health_check():
            print("   ✅ Server is reachable")
        else:
            print("   ❌ Server health check failed")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 2: Edge health check with auth
    print("\n2. Testing edge health (with auth)...")
    try:
        health = api.edge_health_check()
        if health.get('healthy'):
            print("   ✅ Edge API is healthy")
            print(f"   📊 Status: {health}")
        else:
            print(f"   ⚠️  Edge health: {health}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 3: Local sync (get cached data)
    print("\n3. Testing local sync (fetch inventory cache)...")
    try:
        result = api.local_sync(cabinet_id=config['cabinet_id'])
        users = result.get('users', [])
        items = result.get('items', [])
        print(f"   ✅ Sync successful")
        print(f"   📊 {len(users)} users, {len(items)} items cached")
        if users:
            print(f"   👤 First user: {users[0].get('user_name', 'N/A')}")
    except APIError as e:
        print(f"   ❌ API Error: {e}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 4: Authorization test (unknown card)
    print("\n4. Testing card authorization...")
    try:
        result = api.authorize("TEST-UNKNOWN-CARD", config['cabinet_id'])
        if result.get('authorized'):
            print("   ✅ Card authorized (unexpected for unknown card)")
        else:
            print(f"   ✅ Card rejected as expected: {result.get('reason', 'Unknown')}")
    except APIError as e:
        error_str = str(e).lower()
        if 'not registered' in error_str or '403' in error_str:
            print("   ✅ Card correctly rejected (not registered)")
        else:
            print(f"   ❌ API Error: {e}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    print("\n" + "=" * 50)
    print("Test complete")
    print("=" * 50)


if __name__ == "__main__":
    test_connection()
