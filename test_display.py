#!/usr/bin/env python3
"""Quick test for the NiceGUI display."""

import sys
import time
import threading
from pathlib import Path

# Add display to path
sys.path.insert(0, str(Path(__file__).parent / "display"))

try:
    from display import CabinetDisplayGUI
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure nicegui is installed: uv add nicegui")
    sys.exit(1)


def test_sequence(display):
    """Run through display states."""
    time.sleep(2)

    print("State: AUTHENTICATING")
    display.handle_message({
        "type": "STATE_CHANGE",
        "state": "AUTHENTICATING",
        "message": "Reading card..."
    })

    time.sleep(2)

    print("State: UNLOCKED")
    display.handle_message({
        "type": "AUTH_SUCCESS",
        "user": {"name": "Test User", "email": "test@example.com"},
    })

    time.sleep(3)

    print("State: SCANNING")
    display.handle_message({
        "type": "STATE_CHANGE",
        "state": "SCANNING",
        "message": "Checking inventory..."
    })

    time.sleep(2)

    print("State: SUMMARY")
    display.handle_message({
        "type": "SESSION_SUMMARY",
        "summary": {
            "borrowed": [
                {"name": "Arduino Uno"},
                {"name": "Multimeter"}
            ],
            "returned": [
                {"name": "Soldering Iron"}
            ]
        },
        "user_name": "Test User"
    })

    time.sleep(4)

    print("State: LOCKED")
    display.handle_message({
        "type": "STATE_CHANGE",
        "state": "LOCKED",
        "message": "Tap card to unlock"
    })

    print("\nTest complete. Press Ctrl+C to exit.")


def main():
    print("=" * 50)
    print("Smart Cabinet Display Test")
    print("=" * 50)
    print("\nStarting display on http://localhost:8080")
    print("The display will cycle through states automatically.")
    print("\nPress Ctrl+C to exit at any time.")
    print()

    # Create display (windowed mode for testing)
    display = CabinetDisplayGUI(fullscreen=False)

    # Run test sequence in background
    test_thread = threading.Thread(target=test_sequence, args=(display,), daemon=True)
    test_thread.start()

    # Run the display (blocking)
    try:
        display.run()
    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    main()
