#!/usr/bin/env python3
"""Find WHICH tags get missed under the GAPLESS scan, with timing + RSSI.

Runs the configured gapless union scan N times and tracks each EPC's hit rate.
Tags below 100% are the weak ones; their RSSI (weakest seen) tells us how
physically marginal they are. Same-EPC-always-at-bottom + low RSSI => physical
placement (reposition that tag); software tuning can't beat physics.

Run on the Pi:
    python diag_weak_tags.py            # 30 runs (default)
    python diag_weak_tags.py 50
"""
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware.raspberry_pi import RFIDReader, RFID_HOST, RFID_PORT
from config import CONFIG


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    cfg = CONFIG.get('rfid_inventory', {})
    antennas = cfg.get('antennas', [0, 1])
    ant_repeat = cfg.get('ant_repeat', 2)
    settle_ms = cfg.get('settle_ms', 4000)
    min_seconds = cfg.get('min_seconds', 10.0)
    max_seconds = cfg.get('max_seconds', 18.0)

    print(f"Gapless weak-tag diagnostic: {runs} runs "
          f"(ant={antennas}, repeat={ant_repeat}, "
          f"settle={settle_ms}ms, min={min_seconds}s, max={max_seconds}s)")
    print("=" * 64)

    reader = RFIDReader(RFID_HOST, RFID_PORT)
    if not reader.connect():
        print("FAIL: cannot connect to reader")
        return 1

    hit = Counter()            # EPC -> runs it appeared in
    rssi_min = {}              # EPC -> weakest RSSI seen (dBm)
    per_run_counts = []
    per_run_times = []
    try:
        for i in range(1, runs + 1):
            t0 = time.time()
            detail = reader.read_rfid_tags_inventory(
                antennas=antennas, ant_repeat=ant_repeat,
                gapless=True, settle_ms=settle_ms,
                min_seconds=min_seconds, max_seconds=max_seconds,
                return_details=True,
            )
            dt = time.time() - t0
            tags = set(detail['tags'])
            for epc in tags:
                hit[epc] += 1
                r = reader.tag_rssi.get(epc)
                if r is not None:
                    rssi_min[epc] = min(rssi_min.get(epc, r), r)
            per_run_counts.append(len(tags))
            per_run_times.append(dt)
            print(f"  [{i:3d}/{runs}] {len(tags)} tags in {dt:5.2f}s")
    except KeyboardInterrupt:
        runs = len(per_run_counts)
        print(f"\n  Interrupted after {runs} runs")
    finally:
        reader.disconnect()

    if not per_run_counts:
        return 1

    roster = sorted(hit.items(), key=lambda kv: kv[1])   # weakest first

    print("\n" + "=" * 64)
    print(f"Roster: {len(roster)} distinct EPCs ever seen")
    print(f"Per-run count: avg={sum(per_run_counts)/len(per_run_counts):.2f} "
          f"min={min(per_run_counts)} max={max(per_run_counts)}")
    print(f"Per-run time : avg={sum(per_run_times)/len(per_run_times):.2f}s "
          f"min={min(per_run_times):.2f} max={max(per_run_times):.2f}")

    weak = [(e, c) for e, c in roster if c < runs]
    print(f"Always-read (100%): {sum(1 for _, c in roster if c == runs)} / {len(roster)}")
    print(f"Sometimes-missed (<100%): {len(weak)}")

    if weak:
        print(f"\n  {'EPC':<28} {'hits':>9} {'rate':>7} {'minRSSI':>9}")
        for epc, c in weak:
            r = rssi_min.get(epc)
            r_str = f"{r}dBm" if r is not None else "-"
            print(f"  {epc:<28} {c:>4}/{runs} {100*c/runs:>6.1f}% {r_str:>9}")
        print("\n  Low rate + notably weaker RSSI than the rest -> physical: "
              "reposition that tag. Software tuning is already at its ceiling.")
    else:
        print("\nNo weak tags: every EPC read in every run.")

    return 0


if __name__ == '__main__':
    sys.exit(main())
