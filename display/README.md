# Smart Cabinet Pi Display

Local real-time dashboard display for the Smart Cabinet system.

## Overview

This is a web-based display UI that runs locally on the Raspberry Pi, providing real-time visual feedback to users without network latency.

Three modes are available:
1. **NiceGUI Mode** (`display.py`): Pure Python, no npm needed - **RECOMMENDED** (uses uv for dependency management)
2. **Browser Mode** (`index.html` + `launch-display.py`): Legacy file-based IPC
3. **Electron Mode** (legacy): Desktop app with Node.js backend - **DEPRECATED**

## NiceGUI Mode (Recommended)

Pure Python web UI using [NiceGUI](https://nicegui.io/). No npm, no Electron, runs in browser with WebSocket updates.

### Features
- No Node.js/npm dependencies
- Real-time WebSocket updates
- Auto-launches Chromium in kiosk mode
- Mobile-responsive design
- Clean, modern UI

### Usage

```bash
# Install dependencies (from cabinet-pi directory)
uv sync

# Run with main application (automatic)
uv run python -m src.main

# Or test standalone
uv run python display/display.py
```

Then open http://localhost:8080

### Configuration

```json
{
  "display": {
    "enabled": true,
    "fullscreen": true,
    "width": 800,
    "height": 480
  }
}
```

### UI States

| State | Color | Description |
|-------|-------|-------------|
| LOCKED | 🔴 Red | Cabinet locked, waiting for card |
| AUTHENTICATING | 🟡 Yellow | Reading NFC card |
| UNLOCKED | 🟢 Green | Access granted, user info shown |
| SCANNING | 🟡 Yellow | Finalizing session |
| PAIRING | 🔵 Blue | Card pairing mode |
| SUMMARY | 📋 White | Session complete summary |

## Why Local Display?

- **Zero Latency**: Immediate response to card taps
- **Offline Resilient**: Works without internet
- **Better UX**: Smooth animations and instant updates
- **Lower Cost**: No server resources needed
- **Easy Integration**: JavaScript API exposed for Python control

## Quick Start (Browser Mode)

```bash
cd cabinet-pi/display

# Launch display in kiosk mode (production)
python3 launch-display.py

# Or launch in windowed mode (for testing)
python3 launch-display.py --windowed

# Enable demo mode (auto-cycles through states)
python3 launch-display.py --demo
```

## Display UI Features

| State | Visual | Description |
|-------|--------|-------------|
| **LOCKED** | 🔴 Red screen | System locked, waiting for card |
| **AUTHENTICATING** | 🟡 Yellow spinner | Verifying card... |
| **UNLOCKED** | 🟢 Green screen | Welcome, drawers unlocked |
| **SCANNING** | 🟡 Yellow spinner | Checking inventory... |
| **CHECKOUT** | 📋 Summary | Shows borrowed/returned items |

### Additional UI Elements

- **LED Grid**: Shows status of all 4 drawers (green=closed, red=open)
- **Server Status**: Online/offline indicator
- **Sync Status**: Shows pending sync operations
- **Real-time Clock**: Current time display
- **Transaction List**: Recent borrow/return activity

## Installation

### Browser Mode (Recommended)
No installation needed - just Python 3 and Chromium.

```bash
# On Raspberry Pi, ensure Chromium is installed
sudo apt-get install chromium-browser

# Then launch
cd cabinet-pi/display
python3 launch-display.py
```

### Electron Mode (Legacy)
```bash
cd display
npm install
npm start
```

## Communication Protocol

### JavaScript API (Browser Mode)

The display UI exposes a global `window.cabinetDisplay` object for Python integration:

```javascript
// Update system state
cabinetDisplay.updateState('UNLOCKED', {
  userName: '张三',
  userId: 'user-123'
});

// Update LED indicators
cabinetDisplay.updateLEDs([true, false, true, false]);
// true = drawer open (red), false = closed (green)

// Add transaction to list
cabinetDisplay.addTransaction({
  type: 'borrow',  // or 'return'
  item: 'Arduino Uno',
  time: '10:30:45'
});

// Update server/sync status
cabinetDisplay.updateServerStatus(true);  // true = online
cabinetDisplay.updateSyncStatus(true);     // true = sync active
```

### Python Integration Example

```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# Connect to running Chromium instance
options = Options()
options.add_experimental_option("debuggerAddress", "localhost:9222")
driver = webdriver.Chrome(options=options)

# Send state update to display
driver.execute_script("""
  cabinetDisplay.updateState('UNLOCKED', {
    userName: '张三',
    userId: 'user-123'
  });
""")
```

### WebSocket Protocol (Electron Mode - Legacy)

The Electron display communicates via WebSocket on port 8765.

```typescript
interface StateUpdate {
  type: 'STATE_CHANGE' | 'AUTH_SUCCESS' | 'AUTH_FAILURE' |
         'ITEM_SUMMARY' | 'ERROR';
  state: 'LOCKED' | 'AUTHENTICATING' | 'UNLOCKED' | 'SCANNING';
  user?: {
    id: string;
    email: string;
    full_name?: string;
  };
  itemSummary?: {
    borrowed: Array<{tag: string, name: string}>;
    returned: Array<{tag: string, name: string}>;
  };
  error?: string;
}
```

## File Structure

```
display/
├── index.html          # Main display UI (dark theme, responsive)
├── launch-display.py   # Python launcher for kiosk mode
├── test-panel.html     # Test panel for development
├── styles.css          # Legacy Electron styles
├── main.js             # Legacy Electron main process
├── renderer.js         # Legacy Electron renderer
└── README.md           # This file
```

## Keyboard Shortcuts

- `Ctrl+Shift+Q`: Exit kiosk mode (for debugging)
- `F11`: Toggle fullscreen
- `F12`: Open DevTools (if not in kiosk mode)

## Theme

Modern dark theme optimized for Raspberry Pi displays:
- Background: #0a0a0a (near black)
- Card BG: #1a1a2e to #16213e (dark blue gradient)
- Accent: #e94560 (coral red)
- Highlight: #00d9ff (cyan)
- Text: #ffffff (white) / #8892b0 (muted)

## Integration with Python Main Controller

To integrate the display with `main.py`:

1. **Start the display launcher** when the cabinet boots:
```bash
# In /etc/rc.local or systemd service
python3 /home/pi/cabinet-pi/display/launch-display.py --kiosk
```

2. **From Python, send updates** via Chrome DevTools Protocol or file-based IPC:

```python
# cabinet-pi/src/display_client.py
import json
import time
from pathlib import Path

class DisplayClient:
    def __init__(self):
        self.status_file = Path(__file__).parent.parent / 'display' / '.display_status.json'

    def update_state(self, state, user_name=None, user_id=None):
        status = {
            'state': state,
            'user_name': user_name,
            'user_id': user_id,
            'timestamp': time.time()
        }
        self.status_file.write_text(json.dumps(status))

    def add_transaction(self, item_name, action):
        # Append to transaction log
        pass
```

3. **Display reads updates** via JavaScript polling:

```javascript
// In display/index.html
async function pollStatus() {
  try {
    const res = await fetch('.display_status.json');
    const status = await res.json();
    cabinetDisplay.updateState(status.state, {
      userName: status.user_name,
      userId: status.user_id
    });
  } catch (e) {
    // File may not exist yet
  }
}
setInterval(pollStatus, 500); // Poll every 500ms
```
