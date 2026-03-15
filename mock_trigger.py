#!/usr/bin/env python3
"""
Mock hardware trigger utility.

When the main app is running with mock hardware, this script can simulate
NFC card taps by writing to a trigger file.
"""

import sys
import os

def trigger_card(card_uid):
    """Trigger a mock NFC card tap."""
    trigger_file = "/tmp/mock_nfc_trigger.txt"

    with open(trigger_file, 'w') as f:
        f.write(card_uid)

    print(f"✓ Triggered card: {card_uid}")
    print(f"  Written to: {trigger_file}")
    print("  The main app should detect this within 0.5 seconds")


def main():
    print("=" * 50)
    print("Mock NFC Trigger")
    print("=" * 50)
    print()

    if len(sys.argv) > 1:
        card_uid = sys.argv[1]
        trigger_card(card_uid)
    else:
        print("Options:")
        print("  1. CARD-001 (registered test user)")
        print("  2. CARD-002 (unregistered card)")
        print("  3. Enter custom card UID")
        print()

        try:
            choice = input("Select (1-3): ").strip()

            if choice == "1":
                trigger_card("CARD-001")
            elif choice == "2":
                trigger_card("CARD-002")
            elif choice == "3":
                card_uid = input("Enter card UID: ").strip()
                if card_uid:
                    trigger_card(card_uid)
                else:
                    print("No card UID entered")
            else:
                print("Invalid choice")
        except KeyboardInterrupt:
            print("\nCancelled")


if __name__ == "__main__":
    main()
