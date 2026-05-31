#!/usr/bin/env python3
"""Validate the production confirm-union scan: 1 result + N confirm scans,
unioned. Mirrors main.py _scan_rfid exactly so we can see how often the union
reaches the full 81 (and how much each confirm scan backfills).

Run on the Pi:
    python diag_confirm.py            # 3 trials
    python diag_confirm.py 5
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware.raspberry_pi import RFIDReader, RFID_HOST, RFID_PORT
from config import CONFIG

FULL = 81


def main():
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    cfg = CONFIG.get('rfid_inventory', {})
    total = cfg.get('scan_count', 2)

    reader = RFIDReader(RFID_HOST, RFID_PORT)
    if not reader.connect():
        print("FAIL: cannot connect")
        return 1
    reader.disconnect()

    print(f"Union test: {trials} trials, each = {total} scans unioned "
          f"(~{total*15}s/trial)")
    print("=" * 64, flush=True)

    full_hits = 0
    union_sizes = []
    for t in range(1, trials + 1):
        union = set()
        per = []
        for i in range(total):
            scan = set(reader.read_rfid_tags_inventory(
                antennas=cfg.get('antennas', [0, 1]),
                ant_repeat=cfg.get('ant_repeat', 2),
                gapless=True,
                settle_ms=cfg.get('settle_ms', 2000),
                min_seconds=cfg.get('min_seconds', 14.0),
                max_seconds=cfg.get('max_seconds', 16.0),
            ))
            before = len(union)
            union |= scan
            per.append((len(scan), len(union) - before))   # (scan size, +new)
        union_sizes.append(len(union))
        if len(union) >= FULL:
            full_hits += 1
        chain = "  ".join(f"{s}(+{a})" for s, a in per)
        print(f"trial {t}: {chain}  =>  UNION {len(union)}/{FULL}", flush=True)

    reader.disconnect()
    print("=" * 64)
    print(f"Reached full {FULL}: {full_hits}/{trials} trials  "
          f"(union avg={sum(union_sizes)/len(union_sizes):.2f}, min={min(union_sizes)})")
    print("Each '(+n)' is how many tags that confirm scan backfilled. If the")
    print("union reliably hits 81, the confirm scans are doing their job.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
