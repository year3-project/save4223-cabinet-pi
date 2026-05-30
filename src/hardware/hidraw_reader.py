#!/usr/bin/env python3
"""HIDRAW-based NFC/QR reader for NXP HIDKeyBoard devices.

Uses evdev with a background thread for reliable reading.
Based on the working reference implementation from tool-cabinet-pi.
"""

import logging
import threading
import time
import os
import glob
from typing import Optional, Dict

logger = logging.getLogger(__name__)

try:
    from evdev import InputDevice, categorize, ecodes
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False
    logger.warning("evdev not available - HIDRAW reader disabled")

# Key mappings
KEY_MAP = {
    'KEY_A': 'a', 'KEY_B': 'b', 'KEY_C': 'c', 'KEY_D': 'd', 'KEY_E': 'e',
    'KEY_F': 'f', 'KEY_G': 'g', 'KEY_H': 'h', 'KEY_I': 'i', 'KEY_J': 'j',
    'KEY_K': 'k', 'KEY_L': 'l', 'KEY_M': 'm', 'KEY_N': 'n', 'KEY_O': 'o',
    'KEY_P': 'p', 'KEY_Q': 'q', 'KEY_R': 'r', 'KEY_S': 's', 'KEY_T': 't',
    'KEY_U': 'u', 'KEY_V': 'v', 'KEY_W': 'w', 'KEY_X': 'x', 'KEY_Y': 'y',
    'KEY_Z': 'z',
    'KEY_1': '1', 'KEY_2': '2', 'KEY_3': '3', 'KEY_4': '4', 'KEY_5': '5',
    'KEY_6': '6', 'KEY_7': '7', 'KEY_8': '8', 'KEY_9': '9', 'KEY_0': '0',
    'KEY_MINUS': '-', 'KEY_EQUAL': '=', 'KEY_LEFTBRACE': '[', 'KEY_RIGHTBRACE': ']',
    'KEY_BACKSLASH': '\\', 'KEY_SEMICOLON': ';', 'KEY_APOSTROPHE': "'",
    'KEY_GRAVE': '`', 'KEY_COMMA': ',', 'KEY_DOT': '.', 'KEY_SLASH': '/',
    'KEY_SPACE': ' ',
}

SHIFT_MAP = {
    'KEY_A': 'A', 'KEY_B': 'B', 'KEY_C': 'C', 'KEY_D': 'D', 'KEY_E': 'E',
    'KEY_F': 'F', 'KEY_G': 'G', 'KEY_H': 'H', 'KEY_I': 'I', 'KEY_J': 'J',
    'KEY_K': 'K', 'KEY_L': 'L', 'KEY_M': 'M', 'KEY_N': 'N', 'KEY_O': 'O',
    'KEY_P': 'P', 'KEY_Q': 'Q', 'KEY_R': 'R', 'KEY_S': 'S', 'KEY_T': 'T',
    'KEY_U': 'U', 'KEY_V': 'V', 'KEY_W': 'W', 'KEY_X': 'X', 'KEY_Y': 'Y',
    'KEY_Z': 'Z',
    'KEY_1': '!', 'KEY_2': '@', 'KEY_3': '#', 'KEY_4': '$', 'KEY_5': '%',
    'KEY_6': '^', 'KEY_7': '&', 'KEY_8': '*', 'KEY_9': '(', 'KEY_0': ')',
    'KEY_MINUS': '_', 'KEY_EQUAL': '+', 'KEY_LEFTBRACE': '{', 'KEY_RIGHTBRACE': '}',
    'KEY_BACKSLASH': '|', 'KEY_SEMICOLON': ':', 'KEY_APOSTROPHE': '"',
    'KEY_GRAVE': '~', 'KEY_COMMA': '<', 'KEY_DOT': '>', 'KEY_SLASH': '?',
    'KEY_SPACE': ' ',
}

SHIFT_KEYS = {'KEY_LEFTSHIFT', 'KEY_RIGHTSHIFT'}


class HIDRawReader:
    """
    NFC/QR reader using evdev with background thread.

    A background thread continuously reads from the input device so no
    keystroke events are lost.  The foreground caller uses get_scan(timeout)
    to wait for a complete scan (terminated by Enter).
    """

    def __init__(self, device_path: Optional[str] = None):
        self.device_path = device_path
        self._dev: Optional[InputDevice] = None
        self._buffer = ""
        self._shift_pressed = False
        self._result: Optional[str] = None
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False

        if not EVDEV_AVAILABLE:
            return

        if device_path:
            self._open_device(device_path)
        else:
            self._auto_detect()

    def _auto_detect(self) -> bool:
        """Auto-detect NXP HIDKeyBoard device."""
        if not EVDEV_AVAILABLE:
            return False

        try:
            # Check known device path first
            known_paths = [
                '/dev/input/by-id/usb-WCM_HIDKeyBoard_00000000011C-event-kbd',
            ]
            for path in known_paths:
                if os.path.exists(path) and self._open_device(path):
                    return True

            # Fallback: scan all evdev devices
            from evdev import list_devices
            devices = [InputDevice(path) for path in list_devices()]

            for dev in devices:
                if dev.info.vendor == 0x1fc9 and dev.info.product == 0x5aa7:
                    if self._open_device(dev.path):
                        return True

            logger.warning("No HIDRAW NFC/QR reader found")
            return False

        except Exception as e:
            logger.error(f"Auto-detect failed: {e}")
            return False

    def _open_device(self, path: str) -> bool:
        """Open input device and start background reader."""
        try:
            self._dev = InputDevice(path)
            self.device_path = path
            # Start background read loop
            self._running = True
            self._thread = threading.Thread(target=self._scan_loop, daemon=True)
            self._thread.start()
            logger.info(f"HIDRAW reader started: {self._dev.name} at {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to open {path}: {e}")
            self._dev = None
            return False

    def _scan_loop(self):
        """Background thread: continuously read keyboard events."""
        try:
            for event in self._dev.read_loop():
                if not self._running:
                    break
                if event.type == ecodes.EV_KEY:
                    key_event = categorize(event)
                    key = key_event.keycode

                    # Handle shift state
                    if key in SHIFT_KEYS:
                        if key_event.keystate == key_event.key_down:
                            self._shift_pressed = True
                        elif key_event.keystate == key_event.key_up:
                            self._shift_pressed = False
                        continue

                    # Only process key-down events (dedup typematic repeat)
                    if key_event.keystate == key_event.key_down:
                        if key == 'KEY_ENTER':
                            with self._lock:
                                self._result = self._buffer
                                self._event.set()
                            self._buffer = ""
                        elif self._shift_pressed and key in SHIFT_MAP:
                            self._buffer += SHIFT_MAP[key]
                        elif key in KEY_MAP:
                            self._buffer += KEY_MAP[key]
        except Exception as e:
            if self._running:
                logger.error(f"Scan loop error: {e}")

    def is_available(self) -> bool:
        """Check if reader is available."""
        return self._dev is not None and self._running

    def get_scan(self, timeout: Optional[float] = None) -> Optional[str]:
        """Get one complete scan result (blocks until result or timeout)."""
        if self._event.wait(timeout):
            with self._lock:
                result = self._result
                self._result = None
                self._event.clear()
            return result
        return None

    def clear_cache(self):
        """Clear buffered input and pending result."""
        with self._lock:
            self._buffer = ""
            self._result = None
            self._event.clear()

    def read_card(self, timeout: float = 30.0) -> Optional[Dict[str, str]]:
        """
        Read NFC card or QR code.

        Returns:
            Dict with 'type' and 'data' keys, or None if timeout
        """
        if not self.is_available():
            return None

        raw = self.get_scan(timeout=timeout)
        if raw:
            card_type = self._detect_card_type(raw)
            logger.info(f"HIDRAW scan complete ({len(raw)} chars, type={card_type}): {raw[:60]}...")
            return {'type': card_type, 'data': raw}
        return None

    @staticmethod
    def _detect_card_type(data: str) -> str:
        """Detect whether data is NFC UID or QR code."""
        if not data:
            return 'qr'
        cleaned = data.strip().upper()

        # NFC UID: pure digits, 4-14 chars
        if cleaned.isdigit() and 4 <= len(cleaned) <= 14:
            return 'nfc'
        # NFC UID: 8-char hex (4-byte UID)
        if len(cleaned) == 8 and all(c in '0123456789ABCDEF' for c in cleaned):
            return 'nfc'
        # Short mostly-digits: likely NFC
        if 5 <= len(cleaned) <= 10:
            digit_ratio = sum(1 for c in cleaned if c.isdigit()) / len(cleaned)
            if digit_ratio >= 0.7:
                return 'nfc'
        return 'qr'

    @staticmethod
    def clean_hid_input(content: str) -> str:
        """Clean HID keyboard input by removing noise."""
        import re
        if not content:
            return ""
        return re.sub(r'[^a-zA-Z0-9]', '', content)

    def close(self):
        """Stop background thread and close device."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self._dev:
            try:
                self._dev.close()
            except:
                pass
            self._dev = None
        logger.info("HIDRAW reader closed")

    @staticmethod
    def list_devices():
        """List all available input devices."""
        if not EVDEV_AVAILABLE:
            print("evdev not installed. Run: pip install evdev")
            return

        print("\nAvailable input devices:")
        print("-" * 60)
        from evdev import list_devices as ld
        devices = [InputDevice(path) for path in ld()]
        for dev in devices:
            is_nxp = dev.info.vendor == 0x1fc9
            print(f"  {dev.path}: {dev.name} (vendor={hex(dev.info.vendor)}, product={hex(dev.info.product)})")
            if is_nxp:
                print(f"    *** NXP NFC READER ***")
        print()
