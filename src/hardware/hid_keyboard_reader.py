#!/usr/bin/env python3
"""HID Keyboard-based NFC/QR reader.

For readers that emulate keyboards (like NXP HIDKeyBoard).
When a card is scanned, the device sends keystrokes.
"""

import logging
import threading
import time
from typing import Optional, Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import evdev, but provide fallback
try:
    import evdev
    from evdev import InputDevice, categorize, ecodes
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False
    logger.warning("evdev not available - HID keyboard reader disabled")


class HIDKeyboardReader:
    """
    Read from HID keyboard devices (NFC/QR readers that emulate keyboards).

    These devices show up as /dev/input/event* and send keystrokes
    when a card is scanned.
    """

    # Common vendor IDs for NFC/QR keyboard readers
    KNOWN_VENDORS = {
        '1fc9': 'NXP Semiconductors',
        '1234': 'Generic HID',
    }

    def __init__(self, device_path: Optional[str] = None):
        self.device = None
        self.device_path = device_path
        self._buffer = ""
        self._reading = False
        self._callback: Optional[Callable[[str], None]] = None
        self._read_thread: Optional[threading.Thread] = None

        if not EVDEV_AVAILABLE:
            logger.error("evdev library not installed. Run: pip install evdev")
            return

        if device_path:
            self._open_device(device_path)
        else:
            self._auto_detect()

    def _auto_detect(self) -> bool:
        """Auto-detect HID keyboard reader."""
        if not EVDEV_AVAILABLE:
            return False

        try:
            devices = [evdev.InputDevice(path) for path in evdev.list_devices()]

            for dev in devices:
                # Look for keyboard devices that might be NFC readers
                # Skip standard keyboards (usually have more keys)
                caps = dev.capabilities()

                # Check if it's a keyboard (has KEY events)
                if ecodes.EV_KEY in caps:
                    keys = caps[ecodes.EV_KEY]

                    # NFC readers typically have limited keys (just alphanumeric)
                    # Standard keyboards have 100+ keys
                    if len(keys) < 50:
                        logger.info(f"Found potential NFC reader: {dev.name} at {dev.path}")
                        logger.info(f"  Vendor: {hex(dev.info.vendor)}, Product: {hex(dev.info.product)}")

                        if self._open_device(dev.path):
                            return True

            logger.warning("No HID keyboard reader found")
            return False

        except Exception as e:
            logger.error(f"Auto-detect failed: {e}")
            return False

    def _open_device(self, path: str) -> bool:
        """Open a specific input device."""
        try:
            self.device = evdev.InputDevice(path)
            self.device_path = path
            logger.info(f"Opened HID device: {self.device.name} at {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to open {path}: {e}")
            return False

    def _key_to_char(self, keycode: int) -> Optional[str]:
        """Convert keycode to character."""
        # Number keys (0-9)
        if ecodes.KEY_1 <= keycode <= ecodes.KEY_9:
            return str(keycode - ecodes.KEY_1 + 1)
        elif keycode == ecodes.KEY_0:
            return '0'

        # Letter keys (A-Z)
        elif ecodes.KEY_A <= keycode <= ecodes.KEY_Z:
            return chr(ord('A') + keycode - ecodes.KEY_A)

        # Enter/Return key - signals end of scan
        elif keycode == ecodes.KEY_ENTER:
            return '\n'

        return None

    def read_card(self, timeout: float = 30.0) -> Optional[str]:
        """
        Read a card/QR code (blocking).

        Returns:
            The scanned card ID/QR content, or None if timeout
        """
        if not self.device:
            logger.error("No HID device available")
            return None

        start_time = time.time()
        buffer = ""

        logger.info("Waiting for card scan (HID keyboard mode)...")

        try:
            # Grab the device (exclusive access)
            self.device.grab()

            while time.time() - start_time < timeout:
                try:
                    # Read event with short timeout
                    event = self.device.read_one()

                    if event is None:
                        time.sleep(0.01)
                        continue

                    if event.type == ecodes.EV_KEY:
                        key_event = categorize(event)

                        # Only process key down events
                        if key_event.keystate == key_event.key_down:
                            char = self._key_to_char(key_event.scancode)

                            if char == '\n':
                                # End of scan
                                if buffer:
                                    logger.info(f"HID scan complete: {buffer}")
                                    return buffer
                            elif char:
                                buffer += char
                                logger.debug(f"Buffer: {buffer}")

                except Exception as e:
                    logger.error(f"Error reading event: {e}")
                    break

            logger.debug("HID read timeout")
            return None

        finally:
            try:
                self.device.ungrab()
            except:
                pass

    def start_background_read(self, callback: Callable[[str], None]):
        """Start background reading thread."""
        self._callback = callback
        self._reading = True
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._read_thread.start()
        logger.info("Started HID background reader")

    def _read_loop(self):
        """Background read loop."""
        while self._reading:
            try:
                result = self.read_card(timeout=1.0)
                if result and self._callback:
                    self._callback(result)
            except Exception as e:
                logger.error(f"Background read error: {e}")
                time.sleep(1)

    def stop(self):
        """Stop background reading."""
        self._reading = False
        if self._read_thread:
            self._read_thread.join(timeout=2)

    def is_available(self) -> bool:
        """Check if reader is available."""
        return self.device is not None

    @staticmethod
    def list_devices():
        """List all available input devices."""
        if not EVDEV_AVAILABLE:
            print("evdev not installed. Run: pip install evdev")
            return

        print("\nAvailable input devices:")
        print("-" * 60)

        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        for dev in devices:
            caps = dev.capabilities()
            has_keys = ecodes.EV_KEY in caps

            key_count = len(caps.get(ecodes.EV_KEY, []))

            print(f"Path: {dev.path}")
            print(f"  Name: {dev.name}")
            print(f"  Vendor: {hex(dev.info.vendor)}, Product: {hex(dev.info.product)}")
            print(f"  Has keys: {has_keys} ({key_count} keys)")

            if key_count < 50 and key_count > 0:
                print(f"  *** Potential NFC/QR reader (limited keys) ***")
            print()


# Simple test
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        HIDKeyboardReader.list_devices()
    else:
        print("Testing HID Keyboard Reader...")
        print("Scan a card or QR code (Ctrl+C to exit)")
        print()

        reader = HIDKeyboardReader()

        if not reader.is_available():
            print("No reader found. Try: python hid_keyboard_reader.py --list")
            sys.exit(1)

        try:
            while True:
                result = reader.read_card(timeout=30.0)
                if result:
                    print(f"Scanned: {result}")
        except KeyboardInterrupt:
            print("\nExiting...")
