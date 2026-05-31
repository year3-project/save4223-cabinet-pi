#!/usr/bin/env python3
"""A/B benchmark: legacy 3-pass scan vs SDK-style gapless union scan.

Runs both modes R times each on the SAME tags and compares:
  - wall-clock time per scan (speed)
  - unique tags found (accuracy)
  - per-EPC hit rate, with the 3 known weak tags highlighted (accuracy)

Run on the Pi:
    python diag_scan_ab.py            # 15 rounds each (default)
    python diag_scan_ab.py 25
"""
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware.raspberry_pi import RFIDReader, RFID_HOST, RFID_PORT
from config import CONFIG

WEAK = {
    "E28068940000403166A39018",
    "E28068940000403166A4A418",
    "E28068940000403166A48018",
}


def run_mode(reader, cfg, gapless, rounds):
    """Run `rounds` scans in one mode; return (times[], counts[], hit Counter)."""
    times, counts, hit = [], [], Counter()
    for i in range(1, rounds + 1):
        t0 = time.time()
        detail = reader.read_rfid_tags_inventory(
            scan_passes=cfg.get('scan_passes', 3),
            pass_duration=cfg.get('pass_duration', 3.0),
            antennas=cfg.get('antennas', [0, 1]),
            ant_repeat=cfg.get('ant_repeat', 2),
            loop_count=cfg.get('loop_count', 12),
            sessions=cfg.get('sessions'),
            gapless=gapless,
            settle_ms=cfg.get('settle_ms', 700),
            max_seconds=cfg.get('max_seconds', 18.0),
            min_seconds=cfg.get('min_seconds', 8.0),
            return_details=True,
        )
        dt = time.time() - t0
        tags = set(detail['tags'])
        for e in tags:
            hit[e] += 1
        times.append(dt)
        counts.append(len(tags))
        print(f"  [{'GAP' if gapless else 'OLD'} {i:2d}/{rounds}] "
              f"{len(tags)} tags in {dt:.2f}s")
    return times, counts, hit


def summary(label, times, counts, hit, rounds):
    print(f"\n--- {label} ---")
    print(f"  scans         : {rounds}")
    print(f"  avg time      : {sum(times)/len(times):.2f}s "
          f"(min {min(times):.2f}, max {max(times):.2f})")
    print(f"  avg tags      : {sum(counts)/len(counts):.2f} "
          f"(min {min(counts)}, max {max(counts)})")
    print(f"  distinct EPCs : {len(hit)}")
    print(f"  weak-tag hit rate:")
    for e in sorted(WEAK):
        c = hit.get(e, 0)
        print(f"    {e}  {c:>3}/{rounds} = {100*c/rounds:5.1f}%")


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    cfg = CONFIG.get('rfid_inventory', {})

    reader = RFIDReader(RFID_HOST, RFID_PORT)
    if not reader.connect():
        print("FAIL: cannot connect")
        return 1

    print(f"A/B benchmark: {rounds} rounds each mode\n")
    print("=== LEGACY (3-pass + cooldown) ===")
    o_t, o_c, o_h = run_mode(reader, cfg, gapless=False, rounds=rounds)
    print("\n=== GAPLESS (SDK-style continuous) ===")
    g_t, g_c, g_h = run_mode(reader, cfg, gapless=True, rounds=rounds)
    reader.disconnect()

    print("\n" + "=" * 60)
    summary("LEGACY 3-pass", o_t, o_c, o_h, rounds)
    summary("GAPLESS union", g_t, g_c, g_h, rounds)

    spd = (sum(o_t)/len(o_t)) / max(sum(g_t)/len(g_t), 1e-6)
    print(f"\n>>> Gapless is {spd:.2f}x the speed of legacy "
          f"(avg {sum(o_t)/len(o_t):.2f}s -> {sum(g_t)/len(g_t):.2f}s)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
