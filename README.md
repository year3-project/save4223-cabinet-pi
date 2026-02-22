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
# Install Python dependencies
pip install -r requirements.txt

# Install Display (Electron) dependencies
cd display && npm install && cd ..

# Configure
cp config.example.json config.json
# Edit config.json with your settings

# Run (in separate terminals)
python -m src.main          # Main controller
npm --prefix display start  # Dashboard display
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Raspberry Pi                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Main App    │  │   Local DB   │  │   Display    │  │
│  │  (Python)    │  │  (SQLite)    │  │ (Electron)   │  │
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
                              │ HTTP/WebSocket
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

The Pi runs a local dashboard on its connected monitor (via Electron):

- **IDLE**: Welcome screen with instructions
- **AUTHENTICATING**: Loading spinner
- **AUTHENTICATED**: User info with countdown
- **CHECKOUT**: Item summary (borrowed/returned)

### Why Local?

- **Zero Latency**: Immediate response
- **Offline Capable**: Works without internet
- **Better UX**: Smooth 60fps animations

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

## Documentation

See `/home/ada/save4223/docs/pi-implementation-plan.md` for detailed implementation plan.
