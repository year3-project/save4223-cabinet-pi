"""Hardware-free tests for the RFID frame decoder.

These feed synthetic byte streams (built with the reader's own packet builder so
checksums are valid) into the parser to prove the decode logic is correct without
a physical reader. Run: python tests/test_rfid_decode.py
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from hardware.raspberry_pi import RFIDReader, IGNORED_TAGS


def tag_frame(reader, epc_hex, freq_ant=0x00, rssi=0xA0):
    """Build a well-formed inventory tag frame for the given EPC."""
    epc = bytes.fromhex(epc_hex)
    words = len(epc) // 2
    pc = (words << 11) & 0xFFFF
    data = bytes([freq_ant, (pc >> 8) & 0xFF, pc & 0xFF]) + epc + bytes([rssi])
    return reader._build_packet(0x8B, data)


def end_frame(reader, ant=0, read_rate=10, total=2):
    """Build an end-of-inventory status frame (7-byte payload)."""
    data = bytes([ant, (read_rate >> 8) & 0xFF, read_rate & 0xFF]) + total.to_bytes(4, 'big')
    return reader._build_packet(0x8B, data)


EPC_A = "E2000019120123456789ABCD"  # 12-byte / 96-bit EPC
EPC_B = "3034257BF7194E4000000001"


class TestRFIDDecode(unittest.TestCase):

    def setUp(self):
        self.r = RFIDReader()

    def feed(self, *frames):
        self.r._recv_buffer.extend(b''.join(frames))
        self.r._extract_frames_from_buffer()

    def test_single_tag(self):
        self.feed(tag_frame(self.r, EPC_A))
        self.assertEqual(self.r.work_mode_tags, {EPC_A})

    def test_two_tags_plus_end_frame(self):
        self.feed(tag_frame(self.r, EPC_A), tag_frame(self.r, EPC_B), end_frame(self.r))
        # Both tags decoded, end frame NOT misread as a phantom tag.
        self.assertEqual(self.r.work_mode_tags, {EPC_A, EPC_B})
        self.assertTrue(self.r._inventory_done)

    def test_end_frame_sets_done_and_adds_no_tag(self):
        self.feed(end_frame(self.r))
        self.assertEqual(self.r.work_mode_tags, set())
        self.assertTrue(self.r._inventory_done)

    def test_partial_frame_across_chunks(self):
        frame = tag_frame(self.r, EPC_A)
        split = len(frame) // 2
        self.feed(frame[:split])           # first half: nothing decodable yet
        self.assertEqual(self.r.work_mode_tags, set())
        self.feed(frame[split:])           # remainder completes the frame
        self.assertEqual(self.r.work_mode_tags, {EPC_A})

    def test_resync_after_bad_checksum(self):
        # rssi avoids 0xA0 so the corrupt frame contains no false header byte
        # (this protocol has no byte-stuffing; checksum is the real guard).
        bad = bytearray(tag_frame(self.r, EPC_B, rssi=0x55))
        bad[-1] ^= 0xFF                    # corrupt the checksum
        self.feed(bytes(bad), tag_frame(self.r, EPC_A))
        # Corrupt frame dropped, parser resyncs to the next valid frame.
        self.assertIn(EPC_A, self.r.work_mode_tags)
        self.assertNotIn(EPC_B, self.r.work_mode_tags)

    def test_ignored_tag_filtered(self):
        ignored = next(iter(IGNORED_TAGS))
        self.feed(tag_frame(self.r, ignored))
        self.assertNotIn(ignored, self.r.work_mode_tags)

    def test_leading_garbage_before_header(self):
        self.feed(b'\x11\x22\x33' + tag_frame(self.r, EPC_A))
        self.assertEqual(self.r.work_mode_tags, {EPC_A})


if __name__ == '__main__':
    unittest.main(verbosity=2)
