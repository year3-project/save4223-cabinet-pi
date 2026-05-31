#!/usr/bin/env python3
"""Measure whether UNION of K independent short gapless scans guarantees accuracy.

Single-scan reads are probabilistic: the weak tag is caught ~90% of the time.
Union of K independent scans should drive that toward 100% (1 - miss^K) IF the
misses are independent across scans. This quantifies it: for K = 1, 2, 3, run T
trials (each trial = union of K short gapless scans) and report how often the
union reaches the full roster, plus per-weak-tag hit rate and total time.

Each scan disconnects/reconnects (independent: fresh session + frequency re-hop).

Run on the Pi:
    python diag_union.py                 # T=10 trials per K, full roster=80
    python diag_union.py 12 80           # T=12, expected total tags=80
"""
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware.raspberry_pi import RFIDReader, RFID_HOST, RFID_PORT
from config import CONFIG

WEAK = [
    "E28068940000403166A4A418",
    "E28068940000403166A48018",
    "E28068940000403166A39018",
]

# Short per-scan params: grab the easy bulk fast, rely on union for the tail.
SCAN = dict(settle_ms=1200, min_seconds=2.0, max_seconds=5.0)


def one_scan(reader, cfg):
    t0 = time.time()
    detail = reader.read_rfid_tags_inventory(
        antennas=cfg.get('antennas', [0, 1]),
        ant_repeat=cfg.get('ant_repeat', 2),
        gapless=True, return_details=True, **SCAN,
    )
    return set(detail['tags']), time.time() - t0


def main():
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    full = int(sys.argv[2]) if len(sys.argv) > 2 else 80

    cfg = CONFIG.get('rfid_inventory', {})
    reader = RFIDReader(RFID_HOST, RFID_PORT)
    if not reader.connect():
        print("FAIL: cannot connect")
        return 1
    reader.disconnect()

    print(f"Union benchmark: {trials} trials per K, full roster target={full}")
    print(f"Per-scan params: {SCAN}")
    print("=" * 64)

    for K in (1, 2, 3):
        complete = 0
        tag_counts = []
        times = []
        weak_hit = Counter()
        for t in range(1, trials + 1):
            union = set()
            tt = 0.0
            for _ in range(K):
                tags, dt = one_scan(reader, cfg)
                union |= tags
                tt += dt
            tag_counts.append(len(union))
            times.append(tt)
            if len(union) >= full:
                complete += 1
            for w in WEAK:
                if w in union:
                    weak_hit[w] += 1
            print(f"  [K={K}] trial {t:2d}: union={len(union)} in {tt:5.2f}s")
        print(f"  --- K={K}: full-{full} in {complete}/{trials} trials "
              f"({100*complete/trials:.0f}%), "
              f"avg tags={sum(tag_counts)/len(tag_counts):.2f}, "
              f"avg time={sum(times)/len(times):.2f}s")
        for w in WEAK:
            print(f"      {w}: {weak_hit[w]}/{trials} = {100*weak_hit[w]/trials:.0f}%")
        print()

    reader.disconnect()
    print("Read: the smallest K that hits ~100% full-roster is how many union")
    print("scans production should do (stop-when-stable). If even K=3 misses,")
    print("the weak tag is below the physical read floor -> reposition it.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
