# Smart Cabinet Pi Display

Local real-time dashboard display for the Smart Cabinet system.

## Overview

This is an Electron-based display application that runs locally on the Raspberry Pi, providing real-time visual feedback to users without network latency.

## Why Local Display?

- **Zero Latency**: Immediate response to card taps
- **Offline Resilient**: Works without internet
- **Better UX**: Smooth animations and instant updates
- **Lower Cost**: No server resources needed

## Features

| State | Display |
|-------|---------|
| **IDLE** | Welcome screen with instructions |
| **AUTHENTICATING** | Loading spinner |
| **AUTHENTICATED** | User info, session countdown |
| **CHECKOUT** | Item summary (borrowed/returned) |
| **ERROR** | Access denied message |

## Installation

```bash
cd display
npm install
```

## Usage

### Development Mode
```bash
npm run dev
```

### Production Mode (Kiosk)
```bash
npm start
```

### Build for Production
```bash
npm run build
```

## Communication Protocol

The display communicates with the main Python process via WebSocket on port 8765.

### Message Format

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

## Keyboard Shortcuts

- `Ctrl+Shift+Q`: Exit kiosk mode (for debugging)

## Theme

Uses the ISD (Innovation & Smart Design) theme:
- Primary: #F1F7FF (light blue)
- Accent: #003974 (dark blue)
- Secondary: #FFF4F2 (light pink)
