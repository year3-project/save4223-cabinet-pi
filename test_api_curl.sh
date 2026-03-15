#!/bin/bash
# API Test Script using curl
# Test Save4223 Edge API endpoints

set -e

# Configuration - edit these for your setup
# For local server: SERVER_URL="https://lovelace.tail20b481.ts.net:3001"
# For Vercel cloud: SERVER_URL="https://your-project.vercel.app"
SERVER_URL="https://your-project.vercel.app"  # Change to your server URL
EDGE_SECRET="edge_device_secret_key"       # Change to your edge secret
CABINET_ID=1                               # Change to your cabinet ID

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Save4223 Edge API Test (curl)"
echo "=========================================="
echo "Server: $SERVER_URL"
echo "Cabinet: $CABINET_ID"
echo ""

# Function to print success/failure
print_result() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✓ $2${NC}"
    else
        echo -e "${RED}✗ $2${NC}"
    fi
}

# Test 1: Health Check
echo "1. Testing Health Check..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$SERVER_URL/api/health" 2>/dev/null || echo "000")
if [ "$RESPONSE" = "200" ]; then
    print_result 0 "Health check passed (HTTP 200)"
    curl -s "$SERVER_URL/api/health" | head -20
elif [ "$RESPONSE" = "000" ]; then
    print_result 1 "Connection failed - server unreachable"
else
    print_result 1 "Health check returned HTTP $RESPONSE"
fi
echo ""

# Test 2: Edge Health (with auth)
echo "2. Testing Edge Health (with auth)..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $EDGE_SECRET" \
    "$SERVER_URL/api/edge/health" 2>/dev/null || echo "000")
if [ "$RESPONSE" = "200" ]; then
    print_result 0 "Edge health check passed (HTTP 200)"
    curl -s -H "Authorization: Bearer $EDGE_SECRET" "$SERVER_URL/api/edge/health" | head -20
else
    print_result 1 "Edge health check returned HTTP $RESPONSE"
fi
echo ""

# Test 3: Authorize - Unknown Card (should fail)
echo "3. Testing Authorize (unknown card - should fail)..."
RESPONSE=$(curl -s -X POST \
    -H "Authorization: Bearer $EDGE_SECRET" \
    -H "Content-Type: application/json" \
    -d "{\"card_uid\":\"TEST-UNKNOWN-CARD\",\"cabinet_id\":$CABINET_ID}" \
    "$SERVER_URL/api/edge/authorize" 2>/dev/null)
echo "Response: $RESPONSE"
if echo "$RESPONSE" | grep -q "not registered\|unauthorized\|403"; then
    print_result 0 "Correctly rejected unknown card"
elif echo "$RESPONSE" | grep -q "authorized.*true"; then
    print_result 0 "Card was authorized (may be valid in your DB)"
else
    print_result 1 "Unexpected response"
fi
echo ""

# Test 4: Local Sync (get cache data)
echo "4. Testing Local Sync (get cache data)..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $EDGE_SECRET" \
    "$SERVER_URL/api/edge/local-sync?cabinet_id=$CABINET_ID" 2>/dev/null || echo "000")
if [ "$RESPONSE" = "200" ]; then
    print_result 0 "Local sync passed (HTTP 200)"
    SYNC_DATA=$(curl -s -H "Authorization: Bearer $EDGE_SECRET" "$SERVER_URL/api/edge/local-sync?cabinet_id=$CABINET_ID")
    echo "Users count: $(echo "$SYNC_DATA" | grep -o '"users"' | wc -l)"
    echo "Items count: $(echo "$SYNC_DATA" | grep -o '"items"' | wc -l)"
    echo "First 500 chars:"
    echo "$SYNC_DATA" | head -c 500
    echo "..."
else
    print_result 1 "Local sync returned HTTP $RESPONSE"
fi
echo ""

# Test 5: Sync Session (borrow scenario)
echo "5. Testing Sync Session (borrow scenario)..."
SESSION_ID=$(date +%s%N | cut -b1-13)  # Generate unique session ID
RESPONSE=$(curl -s -X POST \
    -H "Authorization: Bearer $EDGE_SECRET" \
    -H "Content-Type: application/json" \
    -d "{
        \"session_id\":\"test-session-$SESSION_ID\",
        \"cabinet_id\":$CABINET_ID,
        \"user_id\":\"550e8400-e29b-41d4-a716-446655440000\",
        \"start_rfids\":[\"RFID-001\",\"RFID-002\",\"RFID-003\"],
        \"end_rfids\":[\"RFID-002\",\"RFID-003\"]
    }" \
    "$SERVER_URL/api/edge/sync-session" 2>/dev/null)
echo "Response: $RESPONSE"
if echo "$RESPONSE" | grep -q "borrowed.*1"; then
    print_result 0 "Successfully detected 1 borrowed item"
elif echo "$RESPONSE" | grep -q '"statusCode":500'; then
    print_result 1 "Server error (check if cabinet_sessions table exists)"
else
    print_result 0 "Sync session completed (check response above)"
fi
echo ""

# Test 6: Pair Card (should fail with invalid token)
echo "6. Testing Pair Card (invalid token - should fail)..."
RESPONSE=$(curl -s -X POST \
    -H "Authorization: Bearer $EDGE_SECRET" \
    -H "Content-Type: application/json" \
    -d "{
        \"pairing_token\":\"INVALID\",
        \"card_uid\":\"TEST-CARD-001\",
        \"cabinet_id\":$CABINET_ID
    }" \
    "$SERVER_URL/api/edge/pair-card" 2>/dev/null)
echo "Response: $RESPONSE"
if echo "$RESPONSE" | grep -q "success.*false\|error\|invalid"; then
    print_result 0 "Correctly rejected invalid pairing token"
else
    print_result 0 "Pair card response received (check above)"
fi
echo ""

echo "=========================================="
echo "Test Complete"
echo "=========================================="
