#!/usr/bin/env python3
"""Hunt phantom (spurious) EPCs and characterize them vs real tags.

Symptom: a gapless scan occasionally reports 81 tags when only 80 exist. A
phantom is a spurious EPC from an uncaught RF bit-error / tag collision; it is
read very few times (1-2) and is usually a 1-2 char variant of a real EPC,
whereas real tags are read many times every run.

For each EPC seen across N runs it reports: how many runs it appeared in, and
its read-count (min/median/max of tag_counter). Then it flags suspected
phantoms = EPCs within small edit distance of a much-more-read EPC.

Run on the Pi:
    python diag_phantom.py            # 15 runs
    python diag_phantom.py 20
"""
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware.raspberry_pi import RFIDReader, RFID_HOST, RFID_PORT
from config import CONFIG


def hexdiff(a, b):
    """Number of differing hex chars (same length only)."""
    if len(a) != len(b):
        return 99
    return sum(1 for x, y in zip(a, b) if x != y)


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    cfg = CONFIG.get('rfid_inventory', {})

    reader = RFIDReader(RFID_HOST, RFID_PORT)
    if not reader.connect():
        print("FAIL: cannot connect")
        return 1

    runs_seen = Counter()            # EPC -> number of runs it appeared in
    read_counts = defaultdict(list)  # EPC -> per-run read count (from tag_counter)
    per_run_total = []
    print(f"Phantom hunt: {runs} gapless runs (~13s each, ~{runs*13//60}min total)",
          flush=True)
    print("=" * 70, flush=True)
    try:
        for i in range(1, runs + 1):
            detail = reader.read_rfid_tags_inventory(
                antennas=cfg.get('antennas', [0, 1]),
                ant_repeat=cfg.get('ant_repeat', 2),
                gapless=True,
                settle_ms=cfg.get('settle_ms', 4000),
                min_seconds=cfg.get('min_seconds', 10.0),
                max_seconds=cfg.get('max_seconds', 18.0),
                return_details=True,
            )
            tags = set(detail['tags'])
            counter = detail.get('tag_counter', {})
            for epc in tags:
                runs_seen[epc] += 1
                read_counts[epc].append(counter.get(epc, 0))
            per_run_total.append(len(tags))
            flag = "  <-- 81!" if len(tags) > 80 else ""
            print(f"  [{i:3d}/{runs}] {len(tags)} tags{flag}", flush=True)
    finally:
        reader.disconnect()

    roster = sorted(runs_seen.items(), key=lambda kv: (kv[1], sum(read_counts[kv[0]])))

    def med(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else 0

    print("\n" + "=" * 70)
    print(f"Distinct EPCs seen: {len(roster)}   (cabinet should have 80)")
    print(f"Per-run total: min={min(per_run_total)} max={max(per_run_total)}")
    print("\nLeast-reliable EPCs (fewest runs / fewest reads first):")
    print(f"  {'EPC':<28} {'runs':>7} {'reads(min/med/max)':>20}")
    for epc, rc in roster[:8]:
        cs = read_counts[epc]
        print(f"  {epc:<28} {rc:>4}/{runs} {min(cs):>6}/{med(cs):>3}/{max(cs):<3}")

    # Suspected phantoms: EPC read few times AND near-identical to a busier EPC.
    busy = {e: sum(read_counts[e]) for e, _ in roster}
    print("\nSuspected phantoms (low reads + near-duplicate of a real EPC):")
    found = False
    for epc, _ in roster:
        total = sum(read_counts[epc])
        if total > 5 * runs:           # read a lot every run -> clearly real
            continue
        for other, _ in roster:
            if other == epc:
                continue
            if busy[other] > 5 * total and hexdiff(epc, other) <= 2:
                d = hexdiff(epc, other)
                print(f"  {epc} (reads~{total}) ~ {other} (reads~{busy[other]})  "
                      f"differs {d} hex char(s)  => PHANTOM of a real tag")
                found = True
                break
    if not found:
        print("  none matched the near-duplicate rule; check the low-read EPCs above.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
