#!/usr/bin/env python3
"""Diagnostic test: try multi-session scanning to find missing 4 tags.

Previous findings:
  - Per-antenna 0x8B union: 35 tags (consistent ceiling)
  - Antenna 2 tags are subset of antenna 1 (no union benefit)
  - 0x8A fast-switch: 36 tags (slightly better)
  - Increasing duration/passes doesn't help beyond 35

Hypothesis: the 4 missing tags may be in Gen2 "already inventoried" state
for session S1 but still visible in other sessions (S0, S2, S3).
Gen2 RFID has 4 independent sessions - cycling through all of them can
catch tags that are "hiding" in one session.

Target: 39 tags.
"""

import sys
import time
import logging
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware.raspberry_pi import RFIDReader

logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')

TARGET_TAGS = 39
POWER = 0x21  # 33dBm
ANTENNAS = [0x00, 0x01]
# Gen2 sessions: S0=0x00, S1=0x01, S2=0x02, S3=0x03
SESSIONS = [0x00, 0x01, 0x02, 0x03]


def scan_multi_session(reader, duration_per_session, antennas, sessions):
    """Scan each antenna x each session combination, union results."""
    all_tags = set()
    tag_counter = Counter()

    for session in sessions:
        for ant in antennas:
            reader._set_antenna(ant)
            time.sleep(0.05)

            # Manual cycle-based scan with specified session
            tag_count = scan_with_session(reader, session, duration_per_session)
            new = set(tag_count.keys()) - all_tags
            all_tags.update(tag_count.keys())
            tag_counter.update(tag_count)

            print(f"    S{session} Ant 0x{ant:02X}: {len(tag_count)} tags, "
                  f"+{len(new)} new (total {len(all_tags)})")
            time.sleep(0.1)

    return all_tags, tag_counter


def scan_with_session(reader, session, duration):
    """Low-level scan with specific session number."""
    tag_count = Counter()
    repeat = 0x01
    start_time = time.time()
    cycle = 0

    reader.work_mode_tags.clear()
    reader._recv_buffer.clear()

    while (time.time() - start_time) < duration:
        # Toggle target each cycle
        target = 0x00 if cycle % 2 == 0 else 0x01
        cmd_payload = bytes([session, target, repeat])

        reader.work_mode_tags.clear()
        packet = reader._build_packet(0x8B, cmd_payload)
        reader.socket.sendall(packet)

        # Receive cycle
        cycle_start = time.time()
        last_data_time = cycle_start
        while (time.time() - cycle_start) < 2.0:
            try:
                reader.socket.settimeout(0.1)
                data = reader.socket.recv(4096)
                if data:
                    last_data_time = time.time()
                    reader._recv_buffer.extend(data)
                    reader._extract_frames_from_buffer()
                else:
                    if (time.time() - last_data_time) > 0.3:
                        break
            except Exception:
                if (time.time() - last_data_time) > 0.3:
                    break

        # Count tags from this cycle
        for tag in reader.work_mode_tags:
            tag_count[tag] += 1

        cycle += 1
        time.sleep(0.3)

    # Process remaining buffer
    if reader._recv_buffer:
        reader._extract_frames_from_buffer()
        for tag in reader.work_mode_tags:
            tag_count[tag] += 1

    return tag_count


def main():
    print("=" * 60)
    print("RFID DIAGNOSTIC: Multi-session + multi-antenna scan")
    print(f"Target: {TARGET_TAGS} tags | Power: 33dBm")
    print("=" * 60)

    results = {}

    # Test 1: Multi-session (all 4 sessions) x both antennas, 4s each
    print("\n[TEST 1] All sessions x both antennas: 4s per combo")
    print("-" * 55)
    reader = RFIDReader()
    try:
        if reader.connect():
            reader._set_output_power(POWER)
            time.sleep(0.1)
            tags, counter = scan_multi_session(reader, 4.0, ANTENNAS, SESSIONS)
            results['4sess_4s'] = tags
            print(f"  => {len(tags)} unique tags")
            if len(tags) >= TARGET_TAGS:
                print(f"  => TARGET REACHED!")
    except Exception as e:
        print(f"  ERROR: {e}")
    finally:
        reader.disconnect()

    # Test 2: Multi-session x both antennas, 8s each
    print("\n[TEST 2] All sessions x both antennas: 8s per combo")
    print("-" * 55)
    reader = RFIDReader()
    try:
        if reader.connect():
            reader._set_output_power(POWER)
            time.sleep(0.1)
            tags, counter = scan_multi_session(reader, 8.0, ANTENNAS, SESSIONS)
            results['4sess_8s'] = tags
            print(f"  => {len(tags)} unique tags")
            if len(tags) >= TARGET_TAGS:
                print(f"  => TARGET REACHED!")
    except Exception as e:
        print(f"  ERROR: {e}")
    finally:
        reader.disconnect()

    # Test 3: Session S0 only (default is S1) x both antennas, 8s
    print("\n[TEST 3] Session S0 only x both antennas: 8s per antenna")
    print("-" * 55)
    reader = RFIDReader()
    try:
        if reader.connect():
            reader._set_output_power(POWER)
            time.sleep(0.1)
            tags, counter = scan_multi_session(reader, 8.0, ANTENNAS, [0x00])
            results['S0_8s'] = tags
            print(f"  => {len(tags)} unique tags")
    except Exception as e:
        print(f"  ERROR: {e}")
    finally:
        reader.disconnect()

    # Comparison
    print("\n" + "=" * 60)
    print("COMPARISON")
    print("=" * 60)
    for name, tags in results.items():
        status = "PASS" if len(tags) >= TARGET_TAGS else "FAIL"
        print(f"  {name}: {len(tags)}/{TARGET_TAGS} tags [{status}]")

    # Show differences between approaches
    if len(results) >= 2:
        keys = list(results.keys())
        best_key = max(results, key=lambda k: len(results[k]))
        best = results[best_key]
        for k in keys:
            if k == best_key:
                continue
            only_in_best = best - results[k]
            only_in_other = results[k] - best
            if only_in_best:
                print(f"\n  Only in {best_key} (not in {k}): {len(only_in_best)} tags")
                for t in sorted(only_in_best):
                    print(f"    {t}")
            if only_in_other:
                print(f"\n  Only in {k} (not in {best_key}): {len(only_in_other)} tags")
                for t in sorted(only_in_other):
                    print(f"    {t}")

    # Show the full tag list from best result
    if results:
        best_key = max(results, key=lambda k: len(results[k]))
        best = results[best_key]
        print(f"\n  Full tag list ({best_key}):")
        for t in sorted(best):
            print(f"    {t}")
    print()


if __name__ == '__main__':
    main()
