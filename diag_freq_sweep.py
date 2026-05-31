#!/usr/bin/env python3
"""Frequency-range experiment: does a higher band (up to 960MHz) read the weak
tags better than the current 865-928?

The 928 ceiling came from an unverified code comment; the reader's factory
default actually ran 860-957.5MHz, so the hardware works above 928. For each
candidate spectrum this script:
  1. Sends the 0x78 custom-spectrum command and checks the reader's ACK
     (ErrorCode 0x10 = accepted; anything else = rejected -> answers "can it
     reach 960?" empirically per band).
  2. Runs N gapless scans and reports total unique tags + the 3 weak tags'
     hit rate (incl. the metal scale A3DC18).

Run on the Pi:
    python diag_freq_sweep.py            # 6 scans per band
    python diag_freq_sweep.py 8
"""
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware.raspberry_pi import RFIDReader, RFID_HOST, RFID_PORT
from config import CONFIG

WEAK = {
    "E28068940000503166A3DC18": "scale A3DC18",
    "E28068940000403166A4A418": "A4A418",
    "E28068940000403166A48018": "A48018",
}

# (start_khz, end_khz, spacing_khz, label) - channel count kept <= 255 (1 byte).
BANDS = [
    (865000, 928000, 250,  "865-928 @250k  [current/baseline]"),
    (865000, 960000, 500,  "865-960 @500k  [wide, reaches 960]"),
    (902000, 960000, 250,  "902-960 @250k  [high band, dense]"),
    (860000, 957500, 2500, "860-957.5 @2.5M [factory default]"),
]


def build_freq_data(start_khz, end_khz, spacing_khz):
    n = (end_khz - start_khz) // spacing_khz + 1
    if not (0 < n <= 255):
        raise ValueError(f"{n} channels out of 1..255")
    space = spacing_khz // 10
    return bytes([0x04, space & 0xFF, n & 0xFF]) + start_khz.to_bytes(3, "big"), n


def apply_band(reader, start, end, spacing):
    """Send the 0x78 spectrum and return (accepted, errorcode, n_channels)."""
    data, n = build_freq_data(start, end, spacing)
    reader.connect()                     # open socket (skips re-init)
    reader.socket.sendall(reader._build_packet(0x78, data))
    time.sleep(0.1)
    status = reader._read_response_status(0x78)
    return (status == 0x10), status, n


def main():
    scans = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    cfg = CONFIG.get('rfid_inventory', {})

    reader = RFIDReader(RFID_HOST, RFID_PORT)
    # Take manual control of frequency: stop connect() from auto-resetting it.
    reader._reader_configured = True
    if not reader.connect():
        print("FAIL: cannot connect")
        return 1
    reader._set_output_power(0x1E)

    print(f"Frequency sweep: {scans} gapless scans per band  (cabinet = 81 tags)")
    print("=" * 70)

    for start, end, spacing, label in BANDS:
        print(f"\n### {label}")
        try:
            accepted, status, n = apply_band(reader, start, end, spacing)
        except ValueError as e:
            print(f"  skip: {e}")
            continue
        sstr = f"0x{status:02X}" if status is not None else "no-ack"
        if not accepted:
            print(f"  REJECTED by reader (ErrorCode={sstr}, {n}ch) "
                  f"-> this band is NOT usable")
            continue
        print(f"  accepted (ack={sstr}, {n} channels). Scanning...")

        hit = Counter()
        totals = []
        for i in range(scans):
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
            for e in tags:
                hit[e] += 1
            totals.append(len(tags))
            print(f"    scan {i+1}/{scans}: {len(tags)} tags", flush=True)

        print(f"  RESULT [{label.split()[0]}]: "
              f"avg={sum(totals)/len(totals):.2f} max={max(totals)} distinct={len(hit)}")
        for epc, name in WEAK.items():
            print(f"    weak {name:<12}: {hit.get(epc,0)}/{scans} = {100*hit.get(epc,0)/scans:.0f}%")

    reader.disconnect()
    print("\nPick the band with the best weak-tag (esp. scale) hit rate; if a")
    print("higher band wins, we make it the production _set_frequency_region.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
