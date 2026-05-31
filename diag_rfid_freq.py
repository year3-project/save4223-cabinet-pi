#!/usr/bin/env python3
"""Read-only RFID reader diagnostic: query CURRENT frequency region + power.

Why: the firmware's _set_frequency_region() sends a malformed 0x78 command that
the reader rejects, so the reader is actually running on its factory-default
frequency. This script asks the reader what frequency region / power it is REALLY
using (0x79 get-frequency, 0x77 get-power), without changing anything.

Run on the Pi (or any host that can reach the reader):
    python diag_rfid_freq.py
    python diag_rfid_freq.py 192.168.0.178 4001
"""
import sys
import socket
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.178"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 4001
ADDR = 0xFF


def checksum(data: bytes) -> int:
    # Manual V4.1.7 p.42: two's complement of sum of ALL bytes incl. 0xA0 header
    return ((~(sum(data) & 0xFF)) + 1) & 0xFF


def build(cmd: int, data: bytes = b"") -> bytes:
    body = bytes([0xA0, len(data) + 3, ADDR, cmd]) + data
    return body + bytes([checksum(body)])


def idx_to_mhz(idx: int) -> float:
    # Frequency parameter table: 0x00-0x06 = 865.0-868.0; 0x07+ = 902.0 stepping 0.5
    return 865.0 + idx * 0.5 if idx <= 6 else 902.0 + (idx - 7) * 0.5


REGION = {0x01: "FCC (902-928MHz)", 0x02: "ETSI (865-868MHz)", 0x03: "CHN (920-925MHz)"}


def recv_all(sock, timeout=0.8) -> bytes:
    sock.settimeout(timeout)
    buf = b""
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        pass
    return buf


def decode_freq(resp: bytes):
    # Find an 0x79 frame in the response
    for i in range(len(resp) - 4):
        if resp[i] == 0xA0 and resp[i + 3] == 0x79:
            ln = resp[i + 1]
            frame = resp[i:i + 2 + ln]
            data = frame[4:-1]
            print(f"  raw 0x79 frame: {frame.hex()}")
            if len(data) >= 3 and data[0] in REGION:        # default-point form
                region, start, end = data[0], data[1], data[2]
                print(f"  >>> MODE: system-default points")
                print(f"  >>> Region : 0x{region:02X} = {REGION.get(region,'?')}")
                print(f"  >>> Start  : idx 0x{start:02X} = {idx_to_mhz(start):.2f} MHz")
                print(f"  >>> End    : idx 0x{end:02X} = {idx_to_mhz(end):.2f} MHz")
                n = end - start + 1
                print(f"  >>> Hopping channels: {n}  ({'FIXED freq - BAD for nulls' if n <= 1 else 'OK'})")
            elif len(data) >= 6 and data[0] == 0x04:         # user-defined form
                space, qty = data[1], data[2]
                sf = (data[3] << 16) | (data[4] << 8) | data[5]
                print(f"  >>> MODE: user-defined")
                print(f"  >>> Start={sf} KHz, spacing={space*10} KHz, channels={qty}")
            else:
                print(f"  >>> Unrecognized 0x79 data: {data.hex()}")
            return
    print("  !! no 0x79 response found (reader may not support it or rejected)")


def decode_power(resp: bytes):
    for i in range(len(resp) - 4):
        if resp[i] == 0xA0 and resp[i + 3] == 0x77:
            ln = resp[i + 1]
            frame = resp[i:i + 2 + ln]
            data = frame[4:-1]
            print(f"  raw 0x77 frame: {frame.hex()}")
            if data:
                if len(data) == 1:
                    print(f"  >>> Power: {data[0]} dBm (all antennas)")
                else:
                    print(f"  >>> Per-antenna power dBm: {[b for b in data]}")
            return
    print("  !! no 0x77 response found")


def main():
    print(f"Connecting to RFID reader {HOST}:{PORT} ...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((HOST, PORT))
    print("Connected.\n")

    print("=== Query CURRENT frequency region (0x79) ===")
    s.sendall(build(0x79))
    time.sleep(0.2)
    decode_freq(recv_all(s))

    print("\n=== Query CURRENT output power (0x77) ===")
    s.sendall(build(0x77))
    time.sleep(0.2)
    decode_power(recv_all(s))

    s.close()
    print("\nDone. Paste this whole output back.")


if __name__ == "__main__":
    main()
