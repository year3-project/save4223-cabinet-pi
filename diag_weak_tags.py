#!/usr/bin/env python3
"""Find WHICH tags get missed, not just how many.

Runs the inventory scan N times and tracks each EPC's hit rate across runs.
Tags that appear in every run are solid; tags below 100% are the weak ones.
If the SAME few EPCs are always at the bottom -> physical placement problem
(reposition those tags). If misses are spread randomly across many EPCs ->
anti-collision / power-margin problem (tune passes/loops/session).

Run on the Pi:
    python diag_weak_tags.py            # 30 runs (default)
    python diag_weak_tags.py 50         # 50 runs
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware.raspberry_pi import RFIDReader, RFID_HOST, RFID_PORT
from config import CONFIG


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    cfg = CONFIG.get('rfid_inventory', {})
    scan_passes = cfg.get('scan_passes', 3)
    pass_duration = cfg.get('pass_duration', 3.0)
    antennas = cfg.get('antennas', [0, 1])
    ant_repeat = cfg.get('ant_repeat', 2)
    loop_count = cfg.get('loop_count', 12)

    print(f"Weak-tag diagnostic: {runs} runs "
          f"({scan_passes}x{pass_duration}s, ant={antennas}, repeat={ant_repeat}, loops={loop_count})")
    print("=" * 60)

    reader = RFIDReader(RFID_HOST, RFID_PORT)
    if not reader.connect():
        print("FAIL: cannot connect to reader")
        return 1

    hit = Counter()        # EPC -> number of runs it appeared in
    per_run_counts = []
    try:
        for i in range(1, runs + 1):
            detail = reader.read_rfid_tags_inventory(
                scan_passes=scan_passes, pass_duration=pass_duration,
                antennas=antennas, ant_repeat=ant_repeat,
                loop_count=loop_count, return_details=True,
            )
            tags = set(detail['tags'])
            for epc in tags:
                hit[epc] += 1
            per_run_counts.append(len(tags))
            print(f"  [{i:3d}/{runs}] {len(tags)} tags")
    except KeyboardInterrupt:
        runs = len(per_run_counts)
        print(f"\n  Interrupted after {runs} runs")
    finally:
        reader.disconnect()

    if not per_run_counts:
        return 1

    roster = sorted(hit.items(), key=lambda kv: kv[1])   # weakest first
    total_seen = len(roster)

    print("\n" + "=" * 60)
    print(f"Roster: {total_seen} distinct EPCs ever seen")
    print(f"Per-run count: avg={sum(per_run_counts)/len(per_run_counts):.2f} "
          f"min={min(per_run_counts)} max={max(per_run_counts)}")

    perfect = [e for e, c in roster if c == runs]
    weak = [(e, c) for e, c in roster if c < runs]
    print(f"Always-read (100%): {len(perfect)} / {total_seen}")
    print(f"Sometimes-missed (<100%): {len(weak)}")

    if weak:
        print("\nWeak tags (lowest hit-rate first):")
        print(f"  {'EPC':<28} {'hits':>6} {'rate':>7}")
        for epc, c in weak:
            print(f"  {epc:<28} {c:>4}/{runs} {100*c/runs:>6.1f}%")
        print("\nReading:")
        print("  - Same 1-3 EPCs always at the bottom -> physical: reposition/"
              "reorient THOSE tags (likely flat on metal or shadowed).")
        print("  - Many EPCs each missed once or twice (rates ~90%+) -> "
              "anti-collision margin: bump scan_passes or loop_count, or toggle session target.")
    else:
        print("\nNo weak tags: every EPC read in every run. Solid.")

    return 0


if __name__ == '__main__':
    sys.exit(main())
