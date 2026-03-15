#!/usr/bin/env python3
"""Hardware test script for Smart Cabinet Pi.

Tests all hardware components:
- NFC/QR reader (USB serial)
- RFID reader (TCP)
- Servos (PCA9685 I2C)
- Drawer switches (GPIO)
- LEDs (GPIO)

Usage:
    python test_hardware.py          # Test all components
    python test_hardware.py --nfc    # Test only NFC
    python test_hardware.py --rfid   # Test only RFID
    python test_hardware.py --servo  # Test only servos
    python test_hardware.py --gpio   # Test only GPIO (switches + LEDs)
"""

import sys
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware import RaspberryPiHardware, DrawerState, LEDColor


def test_nfc_reader(hw):
    """Test NFC/QR reader."""
    print("\n" + "="*50)
    print("TESTING NFC/QR READER")
    print("="*50)

    # Check which reader is available
    if hw._hid_reader and hw._hid_reader.is_available():
        print("Using HID keyboard reader (NXP device)")
    elif hw._nfc_reader and hw._nfc_reader.is_connected():
        print("Using Serial NFC reader")
    else:
        print("WARNING: No NFC reader detected!")
        return False

    print("Please tap a card or scan a QR code...")

    uid = hw.read_nfc(timeout=10)
    if uid:
        print(f"✓ NFC card read: {uid}")
        return True
    else:
        print("✗ No card detected (timeout)")
        return False


def test_rfid_reader(hw):
    """Test RFID reader."""
    print("\n" + "="*50)
    print("TESTING RFID READER")
    print("="*50)
    print("Make sure RFID tags are near the antennas...")

    tags = hw.read_rfid_tags()
    if tags:
        print(f"✓ RFID tags detected: {len(tags)} tags")
        for tag in tags:
            print(f"  - {tag}")
        return True
    else:
        print("✗ No RFID tags detected")
        return False


def test_servos(hw):
    """Test servo motors."""
    print("\n" + "="*50)
    print("TESTING SERVO MOTORS")
    print("="*50)

    print("Unlocking all drawers...")
    hw.unlock_all()
    time.sleep(1)

    input("Press Enter when ready to lock...")

    print("Locking all drawers...")
    hw.lock_all()
    time.sleep(1)

    print("✓ Servo test complete")
    return True


def test_gpio(hw):
    """Test GPIO (drawer switches and LEDs)."""
    print("\n" + "="*50)
    print("TESTING GPIO (SWITCHES + LEDs)")
    print("="*50)

    # Test LEDs
    print("\nTesting LEDs...")
    colors = [LEDColor.RED, LEDColor.GREEN, LEDColor.YELLOW]
    for color in colors:
        print(f"  Setting all LEDs to {color.value}...")
        hw.set_all_leds(color)
        time.sleep(1)

    hw.set_all_leds(LEDColor.OFF)

    # Test drawer switches
    print("\nTesting drawer switches...")
    print("Open and close drawers to test switches.")
    print("Press Ctrl+C to continue...")

    try:
        while True:
            states = hw.get_all_drawer_states()
            status = " | ".join([
                f"D{i}:{s.value}" for i, s in states.items()
            ])
            print(f"\r{status}", end="", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n✓ GPIO test complete")

    return True


def test_all(hw):
    """Run all hardware tests."""
    results = []

    # NFC test
    try:
        results.append(("NFC Reader", test_nfc_reader(hw)))
    except Exception as e:
        print(f"✗ NFC Reader test failed: {e}")
        results.append(("NFC Reader", False))

    # RFID test
    try:
        results.append(("RFID Reader", test_rfid_reader(hw)))
    except Exception as e:
        print(f"✗ RFID Reader test failed: {e}")
        results.append(("RFID Reader", False))

    # Servo test
    try:
        results.append(("Servos", test_servos(hw)))
    except Exception as e:
        print(f"✗ Servo test failed: {e}")
        results.append(("Servos", False))

    # GPIO test
    try:
        results.append(("GPIO", test_gpio(hw)))
    except Exception as e:
        print(f"✗ GPIO test failed: {e}")
        results.append(("GPIO", False))

    # Summary
    print("\n" + "="*50)
    print("TEST SUMMARY")
    print("="*50)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{name}: {status}")

    passed_count = sum(1 for _, p in results if p)
    print(f"\nTotal: {passed_count}/{len(results)} tests passed")

    return all(p for _, p in results)


def main():
    parser = argparse.ArgumentParser(description='Test Smart Cabinet hardware')
    parser.add_argument('--nfc', action='store_true', help='Test only NFC')
    parser.add_argument('--rfid', action='store_true', help='Test only RFID')
    parser.add_argument('--servo', action='store_true', help='Test only servos')
    parser.add_argument('--gpio', action='store_true', help='Test only GPIO')
    parser.add_argument('--all', action='store_true', help='Test all (default)')
    args = parser.parse_args()

    print("="*50)
    print("SMART CABINET PI - HARDWARE TEST")
    print("="*50)
    print("\nInitializing hardware...")

    try:
        hw = RaspberryPiHardware(num_drawers=4)
        hw.initialize()
    except Exception as e:
        print(f"Failed to initialize hardware: {e}")
        return 1

    try:
        # Run selected tests
        if args.nfc:
            success = test_nfc_reader(hw)
        elif args.rfid:
            success = test_rfid_reader(hw)
        elif args.servo:
            success = test_servos(hw)
        elif args.gpio:
            success = test_gpio(hw)
        else:
            success = test_all(hw)

        return 0 if success else 1

    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        return 1

    finally:
        print("\nCleaning up...")
        hw.cleanup()


if __name__ == '__main__':
    sys.exit(main())
