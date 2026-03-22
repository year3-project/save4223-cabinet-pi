#!/usr/bin/env python3
"""Hardware test script for Smart Cabinet Pi.

Tests all hardware components:
- NFC/QR reader (HID keyboard or USB serial)
- RFID reader (TCP socket)
- Locks (GPIO solenoids via relay, active-HIGH)
- Drawer switches (GPIO, PUD_DOWN)
- LEDs (WS2812B strip, 60 pixels, GPIO 18)

Usage:
    uv run python test_hardware.py           # Test all components
    uv run python test_hardware.py --nfc     # Test only NFC
    uv run python test_hardware.py --rfid    # Test only RFID
    uv run python test_hardware.py --locks   # Test only locks
    uv run python test_hardware.py --leds    # Test only LEDs
    uv run python test_hardware.py --gpio    # Test switches + LEDs
    uv run python test_hardware.py --flow    # Full cabinet flow test
"""

import sys
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware import RaspberryPiHardware, DrawerState, LEDColor
from hardware.raspberry_pi import SOLENOID_PINS, DRAWER_SWITCH_PINS, LED_COUNT, RFID_HOST, RFID_PORT


def test_nfc_reader(hw):
    """Test NFC/QR reader."""
    print("\n" + "=" * 50)
    print("TESTING NFC/QR READER")
    print("=" * 50)

    if hw._hid_reader and hw._hid_reader.is_available():
        print("Reader mode: HID keyboard (NXP device)")
    elif hw._nfc_reader and hw._nfc_reader.is_connected():
        print("Reader mode: USB serial")
    else:
        print("WARNING: No NFC reader detected!")
        return False

    print("Tap a card or scan a QR code (10s timeout)...")
    try:
        uid = hw.read_nfc(timeout=10)
        if uid:
            print(f"  PASS  Card UID: {uid}")
            return True
        else:
            print("  FAIL  No card detected (timeout)")
            return False
    except Exception as e:
        print(f"  FAIL  Error: {e}")
        return False


def test_rfid_reader(hw):
    """Test RFID reader (TCP socket)."""
    print("\n" + "=" * 50)
    print("TESTING RFID READER")
    print(f"  Host: {RFID_HOST}:{RFID_PORT}")
    print("=" * 50)
    print("Place RFID tags near the antennas...")

    tags = hw.read_rfid_tags()
    if tags:
        print(f"  PASS  {len(tags)} tag(s) detected:")
        for tag in tags:
            print(f"          {tag}")
        return True
    else:
        print("  FAIL  No RFID tags detected")
        return False


def test_locks(hw):
    """Test solenoid locks via GPIO relays (active-HIGH)."""
    print("\n" + "=" * 50)
    print("TESTING SOLENOID LOCKS")
    print(f"  Pins (BCM): {dict(zip('ABCD', SOLENOID_PINS))}")
    print("  Polarity: ACTIVE-HIGH (HIGH=unlock, LOW=lock)")
    print("=" * 50)

    print("Unlocking all locks (HIGH)...")
    hw.unlock_all()
    input("  Drawers should be unlocked. Press Enter to re-lock...")

    print("Locking all locks (LOW)...")
    hw.lock_all()
    time.sleep(0.5)

    print("  Cycling locks individually (A→B→C→D, 1s each)...")
    for i, name in enumerate("ABCD"):
        print(f"    Lock {name} (GPIO {SOLENOID_PINS[i]}) → unlock")
        hw.unlock_drawer(i)
        time.sleep(1)
        hw.lock_drawer(i)
        print(f"    Lock {name} → locked")
        time.sleep(0.3)

    print("  PASS  Lock test complete")
    return True


def test_leds(hw):
    """Test WS2812B LED strip."""
    print("\n" + "=" * 50)
    print("TESTING WS2812B LED STRIP")
    print(f"  GPIO 18 | {LED_COUNT} pixels | brightness 180")
    print("=" * 50)

    colors = [
        ('red',    'red'),
        ('green',  'green'),
        ('yellow', 'yellow'),
        ('blue',   'blue'),
        ('white',  'white'),
    ]

    for label, color_str in colors:
        print(f"  All LEDs → {label}")
        hw.set_all_leds(color_str)
        time.sleep(0.8)

    print("  Running chase pattern (blue)...")
    hw.led_pattern('chase', 'blue', duration=2.0)

    print("  Running blink pattern (green)...")
    hw.led_pattern('blink', 'green', duration=2.0)

    print("  LEDs off")
    hw.set_all_leds('off')
    print("  PASS  LED test complete")
    return True


def test_gpio(hw):
    """Test drawer switches (GPIO inputs, PUD_DOWN)."""
    print("\n" + "=" * 50)
    print("TESTING DRAWER SWITCHES")
    print(f"  Pins (BCM): {dict(enumerate(DRAWER_SWITCH_PINS))}")
    print("  Pull: PUD_DOWN | HIGH=open, LOW=closed")
    print("=" * 50)
    print("Open and close drawers to verify. Ctrl+C when done.")

    try:
        while True:
            states = hw.get_all_drawer_states()
            status = "  " + " | ".join(
                f"D{i}:{s.value.upper()}" for i, s in states.items()
            )
            print(f"\r{status}    ", end="", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n  PASS  Switch test complete")

    return True


def test_flow(hw):
    """Full cabinet flow: NFC → unlock → RFID scan → lock."""
    print("\n" + "=" * 50)
    print("FULL FLOW TEST")
    print("  NFC auth → unlock → RFID scan → lock")
    print("=" * 50)

    # Step 1: NFC read
    print("\n[1/4] Tap your NFC card (15s timeout)...")
    hw.set_all_leds('yellow')
    card_uid = hw.read_nfc(timeout=15)
    if not card_uid:
        print("  FAIL  No card detected")
        hw.set_all_leds('red')
        return False
    print(f"  Card UID: {card_uid}")

    # Step 2: Unlock
    print("\n[2/4] Unlocking all locks...")
    hw.set_all_leds('green')
    hw.unlock_all()
    print("  All locks unlocked (HIGH)")
    time.sleep(1)

    # Step 3: RFID scan while unlocked
    print("\n[3/4] Scanning RFID inventory...")
    hw.set_all_leds('blue')
    tags = hw.read_rfid_tags()
    if tags:
        print(f"  {len(tags)} tag(s) found:")
        for tag in tags:
            print(f"    {tag}")
    else:
        print("  No RFID tags detected (ok if cabinet is empty)")

    input("\n  Simulate tool borrow/return, then press Enter to close...")

    # Step 4: Lock
    print("\n[4/4] Locking all locks...")
    hw.set_all_leds('red')
    hw.lock_all()
    print("  All locks locked (LOW)")
    time.sleep(1)

    # End scan
    print("  Scanning final RFID state...")
    hw.set_all_leds('yellow')
    end_tags = hw.read_rfid_tags()
    print(f"  End tags: {len(end_tags)}")

    borrowed = [t for t in tags if t not in end_tags]
    returned = [t for t in end_tags if t not in tags]
    print(f"  Diff → borrowed: {len(borrowed)}, returned: {len(returned)}")

    hw.set_all_leds('off')
    print("\n  PASS  Full flow test complete")
    return True


def test_all(hw):
    """Run all hardware tests."""
    results = []

    for label, fn in [
        ("NFC Reader",      lambda: test_nfc_reader(hw)),
        ("RFID Reader",     lambda: test_rfid_reader(hw)),
        ("Locks",           lambda: test_locks(hw)),
        ("LEDs",            lambda: test_leds(hw)),
        ("Drawer Switches", lambda: test_gpio(hw)),
    ]:
        try:
            results.append((label, fn()))
        except Exception as e:
            print(f"  FAIL  {label}: {e}")
            results.append((label, False))

    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)
    for name, passed in results:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    passed_count = sum(1 for _, p in results if p)
    print(f"\n  {passed_count}/{len(results)} passed")
    return all(p for _, p in results)


def main():
    parser = argparse.ArgumentParser(description='Smart Cabinet hardware test')
    parser.add_argument('--nfc',   action='store_true', help='Test NFC reader only')
    parser.add_argument('--rfid',  action='store_true', help='Test RFID reader only')
    parser.add_argument('--locks', action='store_true', help='Test solenoid locks only')
    parser.add_argument('--leds',  action='store_true', help='Test LED strip only')
    parser.add_argument('--gpio',  action='store_true', help='Test drawer switches only')
    parser.add_argument('--flow',  action='store_true', help='Full cabinet flow test')
    args = parser.parse_args()

    print("=" * 50)
    print("SMART CABINET PI - HARDWARE TEST")
    print(f"  Locks:   GPIO {SOLENOID_PINS} (active-HIGH)")
    print(f"  Switches: GPIO {DRAWER_SWITCH_PINS} (PUD_DOWN)")
    print(f"  LEDs:    GPIO 18, {LED_COUNT}px, brightness 180")
    print(f"  RFID:    {RFID_HOST}:{RFID_PORT}")
    print("=" * 50)

    print("\nInitializing hardware...")
    try:
        hw = RaspberryPiHardware(num_drawers=4)
        hw.initialize()
        health = hw.health_check()
        print(f"  NFC:  {health.get('nfc', 'unknown')}")
        print(f"  RFID: {health.get('rfid', 'unknown')}")
    except Exception as e:
        print(f"Hardware init failed: {e}")
        return 1

    try:
        if args.nfc:
            success = test_nfc_reader(hw)
        elif args.rfid:
            success = test_rfid_reader(hw)
        elif args.locks:
            success = test_locks(hw)
        elif args.leds:
            success = test_leds(hw)
        elif args.gpio:
            success = test_gpio(hw)
        elif args.flow:
            success = test_flow(hw)
        else:
            success = test_all(hw)

        return 0 if success else 1

    except KeyboardInterrupt:
        print("\nInterrupted")
        return 1

    finally:
        print("\nCleaning up...")
        hw.set_all_leds('off')
        hw.cleanup()


if __name__ == '__main__':
    sys.exit(main())
