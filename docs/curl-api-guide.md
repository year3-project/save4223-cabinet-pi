# API Testing with curl

Quick reference for testing Save4223 Edge API endpoints.

## Configuration

```bash
# Set your variables
SERVER_URL="https://100.125.135.46:3001"
EDGE_SECRET="edge_device_secret_key"
CABINET_ID=7
```

## Endpoints

### 1. Health Check

```bash
curl -k "$SERVER_URL/api/health"
```

### 2. Edge Health (with auth)

```bash
curl -k -H "Authorization: Bearer $EDGE_SECRET" \
  "$SERVER_URL/api/edge/health"
```

### 3. Authorize Card

**Known card:**
```bash
curl -k -X POST \
  -H "Authorization: Bearer $EDGE_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"card_uid":"CARD-001","cabinet_id":'$CABINET_ID'}' \
  "$SERVER_URL/api/edge/authorize"
```

**Unknown card (should fail):**
```bash
curl -k -X POST \
  -H "Authorization: Bearer $EDGE_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"card_uid":"UNKNOWN-CARD","cabinet_id":'$CABINET_ID'}' \
  "$SERVER_URL/api/edge/authorize"
```

### 4. Sync Session (Borrow)

```bash
curl -k -X POST \
  -H "Authorization: Bearer $EDGE_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id":"test-session-001",
    "cabinet_id":'$CABINET_ID',
    "user_id":"550e8400-e29b-41d4-a716-446655440000",
    "start_rfids":["RFID-001","RFID-002","RFID-003"],
    "end_rfids":["RFID-002","RFID-003"]
  }' \
  "$SERVER_URL/api/edge/sync-session"
```

**Expected result:** 1 item borrowed (RFID-001)

### 5. Sync Session (Return)

```bash
curl -k -X POST \
  -H "Authorization: Bearer $EDGE_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id":"test-session-002",
    "cabinet_id":'$CABINET_ID',
    "user_id":"550e8400-e29b-41d4-a716-446655440000",
    "start_rfids":["RFID-002","RFID-003"],
    "end_rfids":["RFID-001","RFID-002","RFID-003"]
  }' \
  "$SERVER_URL/api/edge/sync-session"
```

**Expected result:** 1 item returned (RFID-001)

### 6. Local Sync (Get Cache Data)

```bash
curl -k -H "Authorization: Bearer $EDGE_SECRET" \
  "$SERVER_URL/api/edge/local-sync?cabinet_id=$CABINET_ID"
```

### 7. Pair Card

```bash
curl -k -X POST \
  -H "Authorization: Bearer $EDGE_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "pairing_token":"ABC12345",
    "card_uid":"NEW-CARD-001",
    "cabinet_id":'$CABINET_ID'
  }' \
  "$SERVER_URL/api/edge/pair-card"
```

## Using the Test Script

```bash
# Make executable
chmod +x test_api_curl.sh

# Edit the SERVER_URL, EDGE_SECRET, and CABINET_ID at the top of the file

# Run all tests
./test_api_curl.sh
```

## Mock Hardware Testing

When using mock hardware, you can trigger NFC events by creating a trigger file:

```bash
# Simulate card tap
echo "CARD-001" > /tmp/mock_nfc_trigger.txt

# The main app will read this file and simulate the card tap
```

Or use the interactive test:

```bash
uv run python interactive_test.py
```

## Troubleshooting

**SSL errors:**
```bash
# Use -k flag to skip SSL verification (development only)
curl -k https://...
```

**Connection refused:**
- Check server is running
- Check firewall: `sudo ufw allow 3000`
- Check Tailscale status: `tailscale status`

**401 Unauthorized:**
- Verify EDGE_SECRET matches server's config
- Check Authorization header format: `Bearer <secret>`

**500 Internal Server Error:**
- Check server logs
- Verify database tables exist
- Check cabinet_sessions table exists
