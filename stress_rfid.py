#!/usr/bin/env python3
"""RFID stress test: run inventory scan 100 times, no lock/unlock."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware.raspberry_pi import RFIDReader, RFID_HOST, RFID_PORT
from config import CONFIG

def main():
    rfid_cfg = CONFIG.get('rfid_inventory', {})
    scan_passes = rfid_cfg.get('scan_passes', 3)
    pass_duration = rfid_cfg.get('pass_duration', 5.0)
    antennas = rfid_cfg.get('antennas', [0, 1])
    ant_repeat = rfid_cfg.get('ant_repeat', 3)
    loop_count = rfid_cfg.get('loop_count', 10)
    sessions = rfid_cfg.get('sessions')

    total_runs = 100
    print(f"RFID Stress Test: {total_runs} runs")
    print(f"  Config: {scan_passes} passes x {pass_duration}s, antennas={antennas}, repeat={ant_repeat}, loops={loop_count}, sessions={sessions}")
    print("=" * 60)

    reader = RFIDReader(RFID_HOST, RFID_PORT)
    if not reader.connect():
        print("FAIL: Cannot connect to RFID reader")
        return 1

    results = []
    try:
        for i in range(1, total_runs + 1):
            detail = reader.read_rfid_tags_inventory(
                scan_passes=scan_passes,
                pass_duration=pass_duration,
                antennas=antennas,
                ant_repeat=ant_repeat,
                loop_count=loop_count,
                return_details=True,
            )
            tags = detail['tags']
            pass_details = detail['pass_details']
            tag_counter = detail['tag_counter']
            count = len(tags)
            results.append(count)
            avg = sum(results) / len(results)
            min_c = min(results)
            max_c = max(results)
            pass_str = ', '.join(f'P{j+1}={n}' for j, n in enumerate(pass_details))
            print(f"  [{i:3d}/{total_runs}] {count} tags ({pass_str})  (avg={avg:.1f}, min={min_c}, max={max_c})")
    except KeyboardInterrupt:
        print(f"\n  Interrupted after {len(results)} runs")
    finally:
        reader.disconnect()

    print("\n" + "=" * 60)
    print(f"RESULTS: {len(results)} runs completed")
    print(f"  Avg: {sum(results)/len(results):.1f}  Min: {min(results)}  Max: {max(results)}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
