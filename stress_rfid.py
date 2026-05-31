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
    # Mirror production (main.py): same gapless params from config so a stress
    # run reproduces exactly one production door-close scan per iteration.
    gapless = rfid_cfg.get('gapless', False)
    settle_ms = rfid_cfg.get('settle_ms', 700)
    min_seconds = rfid_cfg.get('min_seconds', 1.0)
    max_seconds = rfid_cfg.get('max_seconds')

    total_runs = 100
    mode = "GAPLESS continuous" if gapless else f"LEGACY {scan_passes}-pass"
    print(f"RFID Stress Test: {total_runs} runs  [{mode}]")
    if gapless:
        print(f"  Config: antennas={antennas}, repeat={ant_repeat}, "
              f"settle={settle_ms}ms, min={min_seconds}s, max={max_seconds}s, sessions={sessions}")
    else:
        print(f"  Config: {scan_passes} passes x {pass_duration}s, antennas={antennas}, "
              f"repeat={ant_repeat}, loops={loop_count}, sessions={sessions}")
    print("=" * 60)

    reader = RFIDReader(RFID_HOST, RFID_PORT)
    if not reader.connect():
        print("FAIL: Cannot connect to RFID reader")
        return 1

    results = []
    times = []
    try:
        for i in range(1, total_runs + 1):
            t0 = time.time()
            detail = reader.read_rfid_tags_inventory(
                scan_passes=scan_passes,
                pass_duration=pass_duration,
                antennas=antennas,
                ant_repeat=ant_repeat,
                loop_count=loop_count,
                sessions=sessions,
                gapless=gapless,
                settle_ms=settle_ms,
                min_seconds=min_seconds,
                max_seconds=max_seconds,
                return_details=True,
            )
            dt = time.time() - t0
            tags = detail['tags']
            count = len(tags)
            results.append(count)
            times.append(dt)
            avg = sum(results) / len(results)
            print(f"  [{i:3d}/{total_runs}] {count} tags in {dt:5.2f}s  "
                  f"(avg={avg:.1f}, min={min(results)}, max={max(results)})")
    except KeyboardInterrupt:
        print(f"\n  Interrupted after {len(results)} runs")
    finally:
        reader.disconnect()

    print("\n" + "=" * 60)
    print(f"RESULTS: {len(results)} runs completed  [{mode}]")
    print(f"  Tags: avg={sum(results)/len(results):.2f}  min={min(results)}  max={max(results)}")
    if times:
        print(f"  Time: avg={sum(times)/len(times):.2f}s  min={min(times):.2f}  max={max(times):.2f}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
