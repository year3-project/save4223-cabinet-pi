# Step-by-Step Implementation Guide

Complete guide to set up the hybrid edge-cloud architecture.

## Prerequisites

- Raspberry Pi (3B+ or 4 recommended)
- Tailscale account (free)
- Supabase account (free tier)
- Vercel account (free tier)

---

## Phase 1: Set Up Supabase Cloud (30 mins)

### Step 1.1: Create Project

1. Go to [supabase.com/dashboard](https://supabase.com/dashboard)
2. Click "New Project"
3. Name: `save4223`
4. Choose region closest to you
5. Wait for database to provision (~2 mins)

### Step 1.2: Get API Keys

In Project Settings → API:

```
Project URL: https://your-project-ref.supabase.co
anon key:    eyJhbGciOiJIUzI1NiIs... (public)
service_role: eyJhbGciOiJIUzI1NiIs... (secret, keep safe!)
```

Save these for later.

### Step 1.3: Run Database Migrations

Go to SQL Editor → New Query, run:

```sql
-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Profiles (users)
CREATE TABLE profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name TEXT,
    email TEXT UNIQUE NOT NULL,
    role TEXT DEFAULT 'USER' CHECK (role IN ('USER', 'ADMIN')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Locations (cabinets)
CREATE TABLE locations (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    is_restricted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- User Cards (NFC bindings)
CREATE TABLE user_cards (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    card_uid TEXT UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    paired_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    paired_by_cabinet_id INTEGER
);

-- Item Types (tool categories)
CREATE TABLE item_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    max_borrow_duration INTEGER DEFAULT 7, -- days
    embedding VECTOR(768), -- for AI recommendations
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Items (physical RFID-tagged items)
CREATE TABLE items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rfid_tag TEXT UNIQUE NOT NULL,
    item_type_id UUID REFERENCES item_types(id),
    location_id INTEGER REFERENCES locations(id),
    status TEXT DEFAULT 'AVAILABLE' CHECK (status IN ('AVAILABLE', 'BORROWED', 'MAINTENANCE', 'LOST')),
    holder_id UUID REFERENCES profiles(id),
    borrowed_at TIMESTAMP WITH TIME ZONE,
    due_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Cabinet Sessions (from Pi)
CREATE TABLE cabinet_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pi_session_id TEXT UNIQUE NOT NULL,
    cabinet_id INTEGER REFERENCES locations(id),
    user_id UUID REFERENCES profiles(id),
    started_at TIMESTAMP WITH TIME ZONE,
    ended_at TIMESTAMP WITH TIME ZONE,
    synced_from_pi BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Inventory Transactions
CREATE TABLE inventory_transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID REFERENCES cabinet_sessions(id),
    item_id UUID REFERENCES items(id),
    user_id UUID REFERENCES profiles(id),
    action TEXT NOT NULL CHECK (action IN ('BORROW', 'RETURN')),
    rfid_tag TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Pairing Codes (for NFC card pairing)
CREATE TABLE pairing_codes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES profiles(id),
    code TEXT UNIQUE NOT NULL,
    token TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_user_cards_uid ON user_cards(card_uid);
CREATE INDEX idx_items_rfid ON items(rfid_tag);
CREATE INDEX idx_items_location ON items(location_id);
CREATE INDEX idx_items_holder ON items(holder_id);
CREATE INDEX idx_sessions_cabinet ON cabinet_sessions(cabinet_id);
CREATE INDEX idx_transactions_session ON inventory_transactions(session_id);
CREATE INDEX idx_transactions_user ON inventory_transactions(user_id);

-- Enable RLS
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
ALTER TABLE cabinet_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_transactions ENABLE ROW LEVEL SECURITY;

-- RLS Policies (Users can only see their own data)
CREATE POLICY "Users can view own profile" ON profiles
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can view own cards" ON user_cards
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "Users can view items in their location" ON items
    FOR SELECT USING (true); -- Public view

CREATE POLICY "Users can view own sessions" ON cabinet_sessions
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "Users can view own transactions" ON inventory_transactions
    FOR SELECT USING (user_id = auth.uid());
```

### Step 1.4: Insert Test Data

```sql
-- Add test location
INSERT INTO locations (id, name, description) VALUES (1, 'Cabinet 1', 'Main tool cabinet');

-- Add test item types
INSERT INTO item_types (sku, name, description) VALUES
('ARDUINO-001', 'Arduino Uno', 'Arduino Uno R3 microcontroller'),
('RPI-001', 'Raspberry Pi 4', 'Raspberry Pi 4 Model B 4GB'),
('MULTI-001', 'Digital Multimeter', 'UNI-T UT33D multimeter'),
('SOLDER-001', 'Soldering Iron', 'Hakko FX-888D soldering station');

-- Add test items
INSERT INTO items (rfid_tag, item_type_id, location_id) VALUES
('RFID-001', (SELECT id FROM item_types WHERE sku = 'ARDUINO-001'), 1),
('RFID-002', (SELECT id FROM item_types WHERE sku = 'RPI-001'), 1),
('RFID-003', (SELECT id FROM item_types WHERE sku = 'MULTI-001'), 1),
('RFID-004', (SELECT id FROM item_types WHERE sku = 'SOLDER-001'), 1);
```

---

## Phase 2: Deploy to Vercel (20 mins)

### Step 2.1: Prepare Next.js App

On your development machine:

```bash
cd /path/to/server

# Create/update vercel.json
cat > vercel.json << 'EOF'
{
  "version": 2,
  "builds": [
    {
      "src": "package.json",
      "use": "@vercel/next"
    }
  ],
  "routes": [
    {
      "src": "/api/edge/(.*)",
      "dest": "/api/edge/$1"
    }
  ]
}
EOF

# Update next.config.ts for CORS
cat >> next.config.ts << 'EOF'
// Allow Pi to call API
async headers() {
  return [
    {
      source: '/api/edge/:path*',
      headers: [
        { key: 'Access-Control-Allow-Origin', value: '*' },
        { key: 'Access-Control-Allow-Methods', value: 'GET,POST,OPTIONS' },
        { key: 'Access-Control-Allow-Headers', value: 'Authorization, Content-Type' },
      ],
    },
  ]
}
EOF
```

### Step 2.2: Update Edge API to Use Supabase

Create `src/utils/supabase/service.ts`:

```typescript
import { createClient } from '@supabase/supabase-js'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY!

export const supabaseService = createClient(supabaseUrl, serviceRoleKey, {
  auth: {
    autoRefreshToken: false,
    persistSession: false,
  },
})
```

Update edge API routes to use `supabaseService` instead of regular client.

### Step 2.3: Deploy

```bash
# Install Vercel CLI
npm i -g vercel

# Login
vercel login

# Deploy
vercel --prod
```

Note the deployed URL: `https://your-project.vercel.app`

### Step 2.4: Set Environment Variables

In Vercel Dashboard → Project → Settings → Environment Variables:

| Name | Value |
|------|-------|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://your-project-ref.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `your-anon-key` |
| `SUPABASE_SERVICE_ROLE_KEY` | `your-service-role-key` |
| `EDGE_API_SECRET` | `generate-a-random-secret-key` |

Generate a secure edge secret:
```bash
openssl rand -base64 32
```

---

## Phase 3: Configure Raspberry Pi (30 mins)

### Step 3.1: Install uv and Dependencies

On the Pi:

```bash
cd ~/save4223/save4223-cabinet-pi

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# Install dependencies
uv sync
```

### Step 3.2: Create Config

```bash
# Copy cloud config template
cp config.cloud.example.json config.json

# Edit with your values
nano config.json
```

Set:
```json
{
    "server_url": "https://your-project.vercel.app",
    "edge_secret": "your-edge-secret-from-vercel",
    "cabinet_id": 1,
    "db_path": "./data/local.db",
    "session_timeout": 300,
    "rfid_scan_count": 10,
    "sync_interval": 60,
    "num_drawers": 4,
    "hardware": {
        "mode": "mock"
    },
    "ssl": {
        "verify": true,
        "cert_path": null
    },
    "api": {
        "timeout": 10,
        "max_retries": 3,
        "retry_delay": 2
    },
    "display": {
        "enabled": true,
        "fullscreen": true
    }
}
```

### Step 3.3: Test Connection

```bash
uv run python test_connection.py
```

Should show:
```
✓ Server is reachable
✓ Edge health check passed
✓ Sync successful
```

### Step 3.4: Run Initial Sync

```bash
uv run python -c "
from src.api_client import APIClient
from src.local_db import LocalDB
from src.config import CONFIG

api = APIClient(CONFIG['server_url'], CONFIG['edge_secret'])
db = LocalDB(CONFIG['db_path'])

# Pull data from cloud
result = api.local_sync(CONFIG['cabinet_id'])

# Cache users
for user in result.get('users', []):
    if user.get('card_uid'):
        db.cache_auth(user['card_uid'], user, ttl=86400*7)

# Cache items
for item in result.get('items', []):
    db.update_item_cache(
        item['rfid_tag'],
        item['item_id'],
        item['name'],
        item.get('status', 'AVAILABLE'),
        item.get('holder_id')
    )

print(f'Synced {len(result.get(\"users\", []))} users, {len(result.get(\"items\", []))} items')
"
```

---

## Phase 4: Run the System (10 mins)

### Step 4.1: Start Main App

```bash
uv run python -m src.main
```

You should see:
1. Display starts on port 8080
2. Initial sync completes
3. State: LOCKED (red)

### Step 4.2: Test Card Tap

In another terminal:

```bash
# Simulate card tap
uv run python mock_trigger.py
# Select option 1 (CARD-001)
```

On the display:
- Should show AUTHENTICATING (yellow)
- Then UNLOCKED with user info (green)

### Step 4.3: Simulate Checkout

In the console, follow prompts to:
1. Select RFID tags present (start snapshot)
2. Press Enter to "close drawer"
3. Select RFID tags again (end snapshot)
4. See summary of borrowed/returned items
5. Data syncs to cloud in background

### Step 4.4: Verify in Web UI

1. Open `https://your-project.vercel.app`
2. Sign in with test user
3. Check "My Items" - should show borrowed items
4. Check "History" - should show the session

---

## Phase 5: Add Real Hardware (Optional)

### Step 5.1: Update Config

```json
{
    "hardware": {
        "mode": "raspberry_pi",
        "nfc": {
            "type": "pn532",
            "interface": "i2c"
        },
        "rfid": {
            "type": "rc522",
            "ports": [0, 1, 2, 3]
        },
        "servo": {
            "type": "pca9685",
            "i2c_address": "0x40"
        }
    }
}
```

### Step 5.2: Implement Real Hardware Class

Create `src/hardware/raspberry_pi.py` implementing the `HardwareInterface`.

---

## Troubleshooting

### Pi Can't Connect to Vercel

```bash
# Test connectivity
curl -v https://your-project.vercel.app/api/health

# Check if DNS resolves
nslookup your-project.vercel.app
```

### Sync Fails

```bash
# Check pending sync queue
sqlite3 data/local.db "SELECT * FROM pending_sync;"

# Check if auth cache exists
sqlite3 data/local.db "SELECT COUNT(*) FROM auth_cache;"
```

### Display Not Working

```bash
# Test display standalone
uv run python test_display.py

# Check if port 8080 is free
sudo lsof -i :8080
```

---

## Next Steps

1. **Add real NFC/RFID hardware** - Implement `RaspberryPiHardware` class
2. **Set up systemd service** - Auto-start on boot
3. **Configure multiple cabinets** - Add more Pi + cabinet combinations
4. **Set up monitoring** - Add logging/alerts
5. **Mobile app** - Build React Native app for users

---

## Architecture Summary

```
Pi (Edge)                    Vercel (Cloud)              Supabase (DB)
────────────────────────────────────────────────────────────────────────
Card Tap ─────► Local Auth ─────────────────────────────────────────────
                    │
                    ▼
              Local SQLite (cache)
                    │
User Takes ───► RFID Scan ───► Calculate Diff ───► Show Summary ────────
Items                                                  │
                                                       ▼
                                              Queue for Cloud Sync
                                                       │
                                                       ▼
                                               POST /api/edge/sync ───► Save
                                                       │                    │
                                                       ◄────────────────────┘
                                               Background Sync Worker

User Web UI ◄─── Vercel App ◄────────────────── Real-time Data ──────────
```

This gives you:
- ⚡ Fast local response (100ms card tap)
- 🔒 Works offline (local cache)
- ☁️ Cloud visibility (web UI)
- 📱 Mobile access (Vercel app)
- 🔄 Automatic sync (background)
