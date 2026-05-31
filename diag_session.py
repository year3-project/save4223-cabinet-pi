#!/usr/bin/env python3
"""Session sweep using the EXTENDED 0x8A (Len=0x20) inventory command.

Our gapless scan used the BASIC 0x8A (Len=0x0D) which has no Session field, so
the reader runs on its default session. The manual's extended fast-switch 0x8A
exposes Session and RECOMMENDS S2 (建议值 02): with S2's long persistence a tag
goes quiet after one read, clearing the air so physically-weak tags finally win
a slot. This sweeps S0..S3 and reports total + the 3 weak tags, to see whether
session (esp. S2) is the lever the vendor Windows demo had and we didn't.

Run on the Pi:
    python diag_session.py            # ~18s per session
    python diag_session.py 25
"""
import sys
import time
import socket
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hardware.raspberry_pi import RFIDReader, RFID_HOST, RFID_PORT
from config import CONFIG

WEAK = {
    "E28068940000503166A3DC18": "scale A3DC18",
    "E28068940000403166A4A418": "A4A418",
    "E28068940000403166A48018": "A48018",
}


def build_ext_8a(antennas, stay, session, repeat, target=0x00, phase=0x00):
    """Extended cmd_fast_switch_ant_inventory (Len=0x20) data payload.

    [8 x (AntID, Stay)] [Interval] [Reserve x5] [Session] [Target]
    [Optimize] [Ongoing] [TargetQuantity] [Phase] [Repeat]  = 29 bytes.
    Unused antenna slots use ID 0xFF (>7 = skip), Stay 0.
    """
    ants = list(antennas[:8])
    slots = bytearray()
    for i in range(8):
        if i < len(ants):
            slots += bytes([ants[i] & 0xFF, stay & 0xFF])
        else:
            slots += bytes([0xFF, 0x00])
    data = bytes(slots)
    data += bytes([0x00])             # Interval (ms between antennas)
    data += bytes([0x00] * 5)         # Reserve
    data += bytes([session & 0xFF])   # Session  <-- the lever
    data += bytes([target & 0xFF])    # Target (A)
    data += bytes([0x00, 0x00, 0x00]) # Optimize, Ongoing, TargetQuantity (reserved)
    data += bytes([phase & 0xFF])     # Phase
    data += bytes([repeat & 0xFF])    # Repeat (sequence cycles)
    return data


def run_session(reader, antennas, stay, session, repeat, secs):
    pkt = reader._build_packet(0x8A, build_ext_8a(antennas, stay, session, repeat))
    reader._drain_socket(0.3)
    reader._recv_buffer.clear()
    union = set()
    t0 = time.time()
    reader.socket.sendall(pkt)
    while time.time() - t0 < secs:
        try:
            reader.socket.settimeout(0.3)
            d = reader.socket.recv(4096)
            if d:
                reader._recv_buffer.extend(d)
                reader._extract_frames_from_buffer()
                union |= set(reader.work_mode_tags)
                reader.work_mode_tags.clear()
            else:
                reader.socket.sendall(pkt)
        except socket.timeout:
            reader.socket.sendall(pkt)
        except Exception:
            break
    reader._halt_inventory(antennas)
    return union


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 18.0
    cfg = CONFIG.get('rfid_inventory', {})
    antennas = cfg.get('antennas', [0, 1])
    stay = cfg.get('ant_repeat', 2)
    repeat = 10                       # manual 建议值 0x0A

    reader = RFIDReader(RFID_HOST, RFID_PORT)
    if not reader.connect():
        print("FAIL: cannot connect")
        return 1

    print(f"Session sweep (extended 0x8A), {secs:.0f}s each, "
          f"ant={antennas} stay={stay} repeat={repeat}")
    print("=" * 60, flush=True)

    for session in (0, 1, 2, 3):
        union = run_session(reader, antennas, stay, session, repeat, secs)
        print(f"\nS{session}: total unique = {len(union)}", flush=True)
        for epc, name in WEAK.items():
            print(f"    {name:<14}: {'YES' if epc in union else 'no'}")

    reader.disconnect()
    print("\nBest = highest total AND all 3 weak tags = YES. If S2 wins clearly,")
    print("we switch production to the extended 0x8A with Session S2.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
