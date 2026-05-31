#!/usr/bin/env python3
"""Tag-count growth curve: how the unique-tag union grows with scan time.

The vendor Windows demo (UHFDemo / SDKTest) uses the SAME inventory params we
do - Session S1, Target A, repeat 1, fast-switch, continuous (ExecuteTime=-1),
CmdInterval=0 - confirmed from the C# source. Its only edge is that it runs
until the operator stops it, accumulating tags over time. This logs our union
count every ~2s over one long continuous scan, so we can see how long it takes
to reach the full 81 - i.e. whether the accuracy gap is simply run-time.

Run on the Pi:
    python diag_growth.py            # 60s
    python diag_growth.py 90
"""
import sys
import time
import socket
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware.raspberry_pi import RFIDReader, RFID_HOST, RFID_PORT
from config import CONFIG


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    cfg = CONFIG.get('rfid_inventory', {})
    antennas = cfg.get('antennas', [0, 1])
    ant_repeat = cfg.get('ant_repeat', 2)

    reader = RFIDReader(RFID_HOST, RFID_PORT)
    if not reader.connect():
        print("FAIL: cannot connect")
        return 1

    ant = list(antennas[:4])
    while len(ant) < 4:
        ant.append(0x04)
    data = bytes([
        ant[0], ant_repeat if ant[0] != 0x04 else 0,
        ant[1], ant_repeat if ant[1] != 0x04 else 0,
        ant[2], ant_repeat if ant[2] != 0x04 else 0,
        ant[3], ant_repeat if ant[3] != 0x04 else 0,
        0x00, 0xFF,                      # rest=0, loops=0xFF (continuous)
    ])
    pkt = reader._build_packet(0x8A, data)

    reader._drain_socket(0.3)
    reader._recv_buffer.clear()

    union = set()
    first_seen = {}                      # count -> time it was first reached
    print(f"Growth curve over {secs:.0f}s  (freq from config, ant={antennas})")
    print("=" * 50, flush=True)

    t0 = time.time()
    last_log = t0
    reader.socket.sendall(pkt)
    while time.time() - t0 < secs:
        try:
            reader.socket.settimeout(0.3)
            d = reader.socket.recv(4096)
            if d:
                reader._recv_buffer.extend(d)
                reader._extract_frames_from_buffer()
                before = len(union)
                union |= set(reader.work_mode_tags)
                reader.work_mode_tags.clear()
                if len(union) > before:
                    first_seen.setdefault(len(union), round(time.time() - t0, 1))
            else:
                reader.socket.sendall(pkt)       # re-arm if reader idled
        except socket.timeout:
            reader.socket.sendall(pkt)
        except Exception as e:
            print("recv error:", e)
            break

        if time.time() - last_log >= 2.0:
            el = time.time() - t0
            print(f"  t={el:5.1f}s   unique={len(union)}", flush=True)
            last_log = time.time()

    reader._halt_inventory(antennas)
    reader.disconnect()

    print("=" * 50)
    print(f"FINAL: {len(union)} unique tags after {secs:.0f}s continuous")
    for milestone in (78, 79, 80, 81):
        if milestone in first_seen:
            print(f"  reached {milestone} at t={first_seen[milestone]}s")
    print("\nIf it reaches 81 within a few tens of seconds, the Windows-demo")
    print("'accuracy' is just run-time, and we can trade scan time for it.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
