#!/usr/bin/env python3
"""
Control 4 electronic locks (solenoids / maglocks) via GPIO + relays
Pins: GPIO 27, 22, 10, 9 (BCM mode)

Most relay modules are ACTIVE LOW:
  GPIO.LOW  → relay clicks ON → lock powered / unlocked
  GPIO.HIGH → relay OFF       → lock unpowered / locked (fail-secure)

Change ACTIVE_LOW = False if your relays are active HIGH.
"""

import RPi.GPIO as GPIO
import time
import argparse
import sys
from typing import Dict


# ================= CONFIGURATION =================
LOCK_PINS: Dict[str, int] = {
    "A": 27,   # Lock 1
    "B": 22,   # Lock 2
    "C": 10,   # Lock 3
    "D": 9,    # Lock 4
}

ACTIVE_LOW = False          # True = LOW unlocks, False = HIGH unlocks
UNLOCK_TIME = 30.0          # seconds to keep unlocked (typical pulse time)
DEFAULT_LOCK = "A"         # used when no argument given
# =================================================


def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    for name, pin in LOCK_PINS.items():
        GPIO.setup(pin, GPIO.OUT)
        # Set safe default: locked
        if ACTIVE_LOW:
            GPIO.output(pin, GPIO.HIGH)   # HIGH = off = locked
        else:
            GPIO.output(pin, GPIO.LOW)    # LOW = off = locked

    print("All locks initialized → LOCKED")


def unlock(lock_name: str, duration: float = UNLOCK_TIME):
    if lock_name not in LOCK_PINS:
        print(f"Error: Unknown lock '{lock_name}'. Valid: {list(LOCK_PINS.keys())}")
        return

    pin = LOCK_PINS[lock_name]

    try:
        print(f"Unlocking lock {lock_name} (GPIO {pin}) for {duration:.1f} seconds...")

        if ACTIVE_LOW:
            GPIO.output(pin, GPIO.LOW)   # relay ON → unlock
        else:
            GPIO.output(pin, GPIO.HIGH)  # relay ON → unlock

        time.sleep(duration)

    finally:
        # Always return to locked state
        if ACTIVE_LOW:
            GPIO.output(pin, GPIO.HIGH)
        else:
            GPIO.output(pin, GPIO.LOW)

        print(f"Lock {lock_name} → relocked")


def main():
    parser = argparse.ArgumentParser(description="Control 4 electronic locks via relays")
    parser.add_argument("lock", nargs="?", default=DEFAULT_LOCK,
                        help=f"Lock to unlock (A,B,C,D) - default: {DEFAULT_LOCK}")
    parser.add_argument("--time", type=float, default=UNLOCK_TIME,
                        help=f"Unlock duration in seconds (default: {UNLOCK_TIME}s)")
    parser.add_argument("--status", action="store_true",
                        help="Just show current pin states (no action)")
    parser.add_argument("--cycle-all", action="store_true",
                        help="Test: unlock each lock one after another")

    args = parser.parse_args()

    setup_gpio()

    if args.status:
        print("\nCurrent GPIO states:")
        for name, pin in LOCK_PINS.items():
            state = GPIO.input(pin)
            relay = "ON (unlocked)" if (state == 0 if ACTIVE_LOW else state == 1) else "OFF (locked)"
            print(f"  Lock {name} (GPIO {pin:2d}): {relay}  (value={state})")
        sys.exit(0)

    if args.cycle_all:
        print("\nCycling through all locks FOREVER (15 s each + 1 s pause) — Ctrl+C to stop")
        print("───────────────────────────────────────────────────────────────")
        cycle_count = 0
        while True:
            cycle_count += 1
            print(f"\nCycle #{cycle_count} started at {time.strftime('%H:%M:%S')}")
            for name in LOCK_PINS:
                unlock(name, args.time)
                time.sleep(1.0)          # small gap between locks
            print(f"Cycle #{cycle_count} finished")
            time.sleep(2.0)              # optional longer pause between full cycles

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Cleaning up GPIO...")
        GPIO.cleanup()
