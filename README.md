# Smart Cabinet Pi

Raspberry Pi controller for Save4223 Smart Lab Inventory System.

## Overview

This is the edge device software that runs on Raspberry Pi to control:
- NFC/QR code authentication
- RFID tool inventory scanning
- Servo-controlled drawer locks
- LED status indicators
- Local SQLite database for offline operation
- **Local Dashboard Display** - Real-time user feedback

## Quick Start

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Python dependencies
uv sync

# Configure
cp config.example.json config.json
# Edit config.json with your settings

# Run
uv run python -m src.main   # Main controller (display auto-starts)
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Raspberry Pi                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Main App    │  │   Local DB   │  │   Display    │  │
│  │  (Python)    │  │  (SQLite)    │  │  (NiceGUI)   │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                   │         │
│         └─────────────────┴───────────────────┘         │
│                           │                             │
│              WebSocket (state updates)                  │
│                           │                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  NFC/QR      │  │    RFID      │  │   Servos     │  │
│  │  Reader      │  │   Reader     │  │   & LEDs     │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS/REST
                              ▼
                    Save4223 Cloud API
```

## Configuration

Create `config.json`:

```json
{
  "server_url": "http://100.83.123.68:3000",
  "edge_secret": "your-edge-secret-key",
  "cabinet_id": 1,
  "db_path": "/home/pi/cabinet/data/local.db"
}
```

## State Machine

```
LOCKED -> AUTHENTICATING -> UNLOCKED -> SCANNING -> LOCKED
```

## Local Dashboard

The Pi runs a local dashboard using NiceGUI (pure Python, no npm):

- **LOCKED**: Red screen, tap card to unlock
- **AUTHENTICATING**: Yellow spinner
- **UNLOCKED**: Green screen with user info
- **SCANNING**: Yellow spinner, checking inventory
- **SUMMARY**: Shows borrowed/returned items

### Why NiceGUI?

- **Zero Latency**: Immediate WebSocket updates
- **Offline Capable**: Works without internet
- **No npm**: Pure Python, no Node.js dependencies
- **Auto Kiosk**: Auto-launches Chromium in fullscreen

See `display/README.md` for details.

## Hardware

- **NFC Reader**: PN532 (I2C/SPI)
- **RFID Readers**: MFRC522 (SPI) x3
- **Servo Controller**: PCA9685 (I2C)
- **Servos**: SG90 x4
- **LEDs**: WS2812B or standard LEDs
- **Drawer Switches**: Magnetic reed switches

## API Integration

The Pi communicates with Save4223 backend:

- `POST /api/edge/authorize` - Authenticate NFC/QR
- `POST /api/edge/sync-session` - Sync RFID scan results
- `GET /api/edge/local-sync` - Get cached auth/items

## Scripts

### `scripts/full_reset_local_db.py` — Full database reset & re-sync

Wipes **all** local SQLite data and re-fetches users, items, and item types from the remote server. Useful when local cache is stale or corrupted.

```bash
# Interactive (prompts before wiping)
uv run scripts/full_reset_local_db.py

# Skip confirmation prompt
uv run scripts/full_reset_local_db.py --yes

# Skip backup (faster, but no rollback if something goes wrong)
uv run scripts/full_reset_local_db.py --no-backup
```

The script auto-detects if the database file is owned by root and re-executes itself with `sudo` when needed. A timestamped backup is saved to `data/local.db.bak.YYYYMMDD_HHMMSS` by default.

## Documentation

See `/home/ada/save4223/docs/pi-implementation-plan.md` for detailed implementation plan.
