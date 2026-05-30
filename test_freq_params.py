#!/usr/bin/env python3
"""RFID frequency parameter sweep test.

Tries different frequency region configurations on the reader and compares
tag detection rates.  Each config is tested with multiple scan passes; the
script reports total unique tags and per-pass consistency.

Frequency region command 0x78, mode 2 (user-defined spectrum):
  Data: [0x02] [start_freq_2] [start_freq_1] [start_freq_0]
        [freq_space] [freq_quantity_H] [freq_quantity_L]

  - start_freq: 3-byte big-endian, unit = KHz
  - freq_space: 1 byte, unit = 10 KHz  (e.g. 0x14 = 200 KHz)
  - freq_quantity: 2-byte big-endian, number of channels

Usage:
    uv run test_freq_params.py
    uv run test_freq_params.py --passes 3 --duration 3
    uv run test_freq_params.py --quick          # fewer passes, shorter duration
"""

import argparse
import socket
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware.raspberry_pi import RFIDReader, RFID_HOST, RFID_PORT, RFID_ADDRESS

# ---------------------------------------------------------------------------
# Frequency configurations to test
# ---------------------------------------------------------------------------
# Each entry: (label, start_khz, spacing_khz, end_khz)
# The script calculates channel count automatically.

FREQ_CONFIGS = [
    # --- Compare 865-928 vs 865-960 ---
    ("865-928 200kHz (316ch)",   865000, 200, 928000),
    ("865-960 200kHz (476ch)",   865000, 200, 960000),

    # # --- narrower range, denser channels ---
    # ("865-940 100kHz",   865000, 100, 940000),
    # ("865-928 100kHz",   865000, 100, 928000),
    #
    # # --- extend upper bound ---
    # ("865-960 100kHz",   865000, 100, 960000),
    #
    # # --- FCC ISM band centered ---
    # ("902-928 200kHz",   902000, 200, 928000),
    # ("902-928 100kHz",   902000, 100, 928000),
    # ("902-960 200kHz",   902000, 200, 960000),
    # ("902-960 100kHz",   902000, 100, 960000),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def khz_to_3bytes(khz: int) -> bytes:
    """Convert frequency in KHz to 3-byte big-endian."""
    return khz.to_bytes(3, 'big')


def build_freq_command(start_khz: int, spacing_khz: int, end_khz: int) -> bytes:
    """Build the data payload for command 0x78 mode 2."""
    start = khz_to_3bytes(start_khz)
    space_val = spacing_khz // 10          # unit = 10 KHz
    n_channels = (end_khz - start_khz) // spacing_khz
    return (
        bytes([0x02])
        + start
        + bytes([space_val & 0xFF])
        + n_channels.to_bytes(2, 'big')
    )


def send_freq_config(reader: RFIDReader, start_khz: int, spacing_khz: int, end_khz: int):
    """Apply a frequency region configuration to the reader."""
    data = build_freq_command(start_khz, spacing_khz, end_khz)
    packet = reader._build_packet(0x78, data)
    reader.socket.sendall(packet)
    time.sleep(0.15)
    reader.socket.settimeout(0.5)
    try:
        reader.socket.recv(4096)
    except socket.timeout:
        pass


def scan_once(reader: RFIDReader, pass_duration: float, antennas: list,
              ant_repeat: int, loop_count: int) -> dict:
    """Run one inventory scan and return detail dict."""
    return reader.read_rfid_tags_inventory(
        scan_passes=1,
        pass_duration=pass_duration,
        antennas=antennas,
        ant_repeat=ant_repeat,
        loop_count=loop_count,
        return_details=True,
    )

# ---------------------------------------------------------------------------
# Main test loop
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="RFID frequency parameter sweep")
    parser.add_argument("--passes", type=int, default=3, help="Scan passes per config")
    parser.add_argument("--duration", type=float, default=3.0, help="Seconds per pass")
    parser.add_argument("--quick", action="store_true", help="1 pass x 2s (fast sweep)")
    parser.add_argument("--antennas", type=str, default="0,1", help="Comma-separated antenna IDs")
    parser.add_argument("--power", type=lambda x: int(x, 0), default=0x21, help="Power dBm hex (default 0x21=33dBm)")
    args = parser.parse_args()

    if args.quick:
        args.passes = 1
        args.duration = 2.0

    antennas = [int(a.strip(), 0) for a in args.antennas.split(",")]
    ant_repeat = 2
    loop_count = 12

    print("=" * 65)
    print("  RFID Frequency Parameter Sweep")
    print(f"  {args.passes} pass(es) x {args.duration}s | antennas={antennas} | power=0x{args.power:02X}")
    print("=" * 65)

    results = {}

    for idx, (label, start, spacing, end) in enumerate(FREQ_CONFIGS):
        n_ch = (end - start) // spacing
        print(f"\n[{idx+1}/{len(FREQ_CONFIGS)}] {label}  ({n_ch} channels, {start//1000}-{end//1000} MHz)")
        print("-" * 55)

        reader = RFIDReader(RFID_HOST, RFID_PORT)
        try:
            if not reader.connect():
                print("  SKIP: cannot connect")
                continue

            reader._set_output_power(args.power)
            time.sleep(0.05)

            # Apply custom frequency
            try:
                send_freq_config(reader, start, spacing, end)
            except Exception as e:
                print(f"  WARN: freq command failed: {e}")

            # Run passes
            pass_counts = []
            all_tags = set()
            tag_counter = Counter()

            for p in range(args.passes):
                detail = scan_once(
                    reader, args.duration, antennas,
                    ant_repeat, loop_count,
                )
                tags = detail['tags']
                pc = detail['pass_details']
                new = set(tags) - all_tags
                all_tags.update(tags)
                tag_counter.update(detail.get('tag_counter', {}))
                pass_counts.append(len(tags))
                print(f"  pass {p+1}: {len(tags)} tags (+{len(new)} new) "
                      f"[{', '.join(str(x) for x in pc)}]")
                time.sleep(0.3)

            results[label] = {
                'all_tags': all_tags,
                'tag_counter': tag_counter,
                'pass_counts': pass_counts,
                'min': min(pass_counts),
                'max': max(pass_counts),
                'avg': sum(pass_counts) / len(pass_counts),
            }
            print(f"  => total unique: {len(all_tags)} | "
                  f"per-pass min/max/avg: {min(pass_counts)}/{max(pass_counts)}/{sum(pass_counts)/len(pass_counts):.1f}")

        except Exception as e:
            print(f"  ERROR: {e}")
        finally:
            reader.disconnect()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 65)
    print("  SUMMARY (sorted by unique tags, descending)")
    print("=" * 65)
    print(f"  {'Config':<22} {'Unique':>6} {'Min':>5} {'Max':>5} {'Avg':>6}")
    print("  " + "-" * 50)

    sorted_results = sorted(results.items(), key=lambda x: len(x[1]['all_tags']), reverse=True)
    for label, r in sorted_results:
        n = len(r['all_tags'])
        marker = " <-- BEST" if n == len(sorted_results[0][1]['all_tags']) else ""
        print(f"  {label:<22} {n:>6} {r['min']:>5} {r['max']:>5} {r['avg']:>6.1f}{marker}")

    # Show unique tags from best config
    if sorted_results:
        best_label, best = sorted_results[0]
        print(f"\n  Best config: {best_label} — {len(best['all_tags'])} unique tags")
        print(f"  Tags:")
        for t in sorted(best['all_tags']):
            count = best['tag_counter'].get(t, 0)
            print(f"    {t}  (seen {count}x)")

    print()


if __name__ == '__main__':
    main()
