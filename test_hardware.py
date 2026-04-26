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
import threading
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware import RaspberryPiHardware, DrawerState, LEDColor
from hardware.raspberry_pi import SOLENOID_PINS, DRAWER_SWITCH_PINS, LED_COUNT, RFID_HOST, RFID_PORT
from pairing_handler import PairingHandler
from config import CONFIG

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


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
        # Use the auto-detect method instead of read_nfc
        result = hw.read_card_auto(timeout=10)
        if result:
            raw_data = result['data']
            card_type = result['type']

            # Try to extract token if it's a QR
            pairing_handler = PairingHandler(None, None)
            token = pairing_handler.extract_token_from_qr(raw_data) if card_type == 'qr' else None

            display_type = "QR (Pairing Token)" if token else card_type.upper()
            print(f"  PASS  Raw: {raw_data}")
            print(f"  Type: {display_type}")
            if token:
                print(f"  Token: {token}")
            return True
        else:
            print("  FAIL  No card detected (timeout)")
            return False
    except Exception as e:
        print(f"  FAIL  Error: {e}")
        return False


def test_rfid_reader(hw, quick=False):
    """Test RFID reader (TCP socket) with voting mechanism."""
    rfid_inv_cfg = CONFIG.get('rfid_inventory', {})
    antennas = rfid_inv_cfg.get('antennas')

    if quick:
        scan_passes = rfid_inv_cfg.get('quick_passes', 1)
        pass_duration = rfid_inv_cfg.get('quick_duration', 2.0)
        label = f"QUICK SCAN (~{pass_duration:.0f}s)"
    else:
        scan_passes = rfid_inv_cfg.get('scan_passes', 3)
        pass_duration = rfid_inv_cfg.get('pass_duration', 5.0)
        label = "INVENTORY MODE"

    print("\n" + "=" * 50)
    print(f"TESTING RFID READER ({label})")
    print(f"  Host: {RFID_HOST}:{RFID_PORT}")
    print(f"  Config: {scan_passes} passes x {pass_duration}s, antennas={antennas}")
    print("=" * 50)
    print("Place RFID tags near the antennas...")

    # Unlock cabinet so user can freely add/remove items while testing
    hw.unlock_all()

    tags = hw.read_rfid_tags_inventory(
        scan_passes=scan_passes,
        pass_duration=pass_duration,
        antennas=antennas,
    )

    if tags:
        print(f"  PASS  {len(tags)} confirmed tag(s)")
        return True
    else:
        print("  No RFID tags detected")
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
    
    print("  Running blink pattern (red)...")
    hw.led_pattern('blink', 'red', duration=2.0)

    # Normal idle state
    print("  Running rainbow pattern...")
    hw.led_pattern('rainbow', 'white', duration=2.0)

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

    def start_led(pattern: str, color, duration: float = 1.0):
        stop_event = threading.Event()

        def _run():
            while not stop_event.is_set():
                hw.led_pattern(pattern, color, duration)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return stop_event, t

    def stop_led(handle):
        if not handle:
            return
        stop_event, thread = handle
        stop_event.set()
        thread.join(timeout=2)

    # # Idle rainbow (non-blocking)
    # idle_handle = start_led('rainbow', 'white', duration=1.0)

    # Step 1: Pre-scan RFID before auth (blue chase while scanning)
    print("\n[1/6] Pre-scan RFID inventory (baseline)...")
    scan_handle = start_led('chase', 'blue', duration=0.5)
    start_tags = hw.read_rfid_tags_voting() or []
    stop_led(scan_handle)
    if start_tags:
        print(f"  Baseline: {len(start_tags)} tag(s)")
    else:
        print("  Baseline: no tags detected (ok if empty)")

    # Step 2: NFC auth
    print("\n[2/6] Tap your NFC card to unlock (15s timeout)...")
    card_uid = hw.read_nfc(timeout=15)
    if not card_uid:
        print("  FAIL  No card detected")
        hw.set_all_leds('red')
        return False
    print(f"  Card UID: {card_uid}")

    # Auth success: stay green (no more blue chase)
    hw.set_all_leds('green')

    # Step 3: Unlock (auth success)
    print("\n[3/6] Unlocking all locks...")
    hw.unlock_all()
    print("  All locks unlocked (HIGH)")
    time.sleep(0.5)

    # Step 4: Wait for completion tap (stay green while waiting)
    print("\n[4/6] Tap card again when finished (15s timeout)...")
    done_uid = hw.read_nfc(timeout=15)
    if not done_uid:
        print("  FAIL  No completion tap detected")
        hw.set_all_leds('red')
        return False
    print(f"  Completion card: {done_uid}")

    # If drawers open at completion tap, flash red twice as warning
    if not hw.are_all_drawers_closed():
        for _ in range(2):
            hw.set_all_leds('red')
            time.sleep(0.3)
            hw.set_all_leds('off')
            time.sleep(0.2)
        hw.set_all_leds('red')

    # Step 5: Ensure drawers closed before locking (no timeout; wait indefinitely)
    print("\n[5/6] Checking drawers are closed before locking...")
    drawers_closed = hw.are_all_drawers_closed()
    while not drawers_closed:
        hw.set_all_leds('red')
        time.sleep(0.2)
        drawers_closed = hw.are_all_drawers_closed()
    hw.set_all_leds('green')

    # Lock
    print("  Locking all locks...")
    hw.set_all_leds('red' if not drawers_closed else 'green')
    hw.lock_all()
    print("  All locks locked (LOW)")
    time.sleep(0.5)

    # Step 6: Post-lock RFID scan and diff (blue chase while scanning)
    print("\n[6/6] Post-lock RFID inventory...")
    scan_handle = start_led('chase', 'blue', duration=0.5)
    end_tags = hw.read_rfid_tags_voting() or []
    stop_led(scan_handle)
    print(f"  End tags: {len(end_tags)}")

    borrowed = [t for t in start_tags if t not in end_tags]
    returned = [t for t in end_tags if t not in start_tags]
    print(f"  Diff → borrowed: {len(borrowed)}, returned: {len(returned)}")

    # Idle rainbow resumes
    # idle_handle = start_led('rainbow', 'white', duration=1.0)
    # time.sleep(2.0)
    # stop_led(idle_handle)

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
    parser.add_argument('--rfid',  action='store_true', help='Test RFID reader only (full inventory)')
    parser.add_argument('--rfid-quick', action='store_true', help='Quick RFID scan (~2s)')
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
        elif args.rfid_quick:
            success = test_rfid_reader(hw, quick=True)
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
