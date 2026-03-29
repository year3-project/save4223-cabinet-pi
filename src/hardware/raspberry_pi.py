#!/usr/bin/env python3
"""Raspberry Pi hardware implementation for Smart Cabinet.

Real hardware control for production deployment.
Based on legacy implementation, adapted for new architecture.
"""

import time
import logging
import threading
import socket
import glob
from typing import List, Optional, Dict, Any
from pathlib import Path

try:
    import RPi.GPIO as GPIO
    from rpi_ws281x import PixelStrip, Color
    import serial
    RPI_AVAILABLE = True
except ImportError as e:
    RPI_AVAILABLE = False
    logging.warning(f"RPi libraries not available ({e}) - running in simulation mode")

from .base import HardwareInterface, DrawerState, LEDColor

logger = logging.getLogger(__name__)


# Configuration constants
SOLENOID_PINS = [27, 22, 10, 9]  # Lock A -> D  (ACTIVE_LOW=False: HIGH=unlock, LOW=lock)
DRAWER_SWITCH_PINS = [26, 19, 6, 5]  # Switches 1 -> 4 (PUD_DOWN: HIGH=open)

# WS2812B configuration
LED_COUNT = 60       # Number of LED pixels
LED_PIN = 18         # GPIO pin connected to the pixels (18 uses PWM!)
LED_FREQ_HZ = 800000 # LED signal frequency in hertz (usually 800khz)
LED_DMA = 10         # DMA channel to use for generating signal (try 10)
LED_BRIGHTNESS = 180 # ~70% brightness
LED_INVERT = False   # True to invert the signal (when using NPN transistor level shift)
LED_CHANNEL = 0      # set to '1' for GPIOs 13, 19, 41, 45 or 53

# RFID configuration
RFID_HOST = '192.168.0.178'
RFID_PORT = 4001
RFID_READ_CYCLES = 8
RFID_READ_INTERVAL = 1.0
RFID_ADDRESS = 0xFF
IGNORED_TAGS = {"00B07A15306008EFF68E8F54"}

# NFC/QR configuration
NFC_BAUD_RATE = 115200


class NFCQRReader:
    """USB NFC/QR code reader with improved format detection."""

    def __init__(self):
        self.ser = None
        self._auto_detect_port()

    def _auto_detect_port(self):
        """Auto-detect USB serial device."""
        usb_patterns = ['/dev/ttyUSB*', '/dev/ttyACM*']

        for pattern in usb_patterns:
            ports = glob.glob(pattern)
            for port in ports:
                if self._try_connect(port):
                    logger.info(f"NFC/QR reader connected at {port}")
                    return

        logger.warning("No USB NFC/QR reader found")

    def _try_connect(self, port: str) -> bool:
        """Try to connect to specified serial port."""
        if not RPI_AVAILABLE:
            return False

        try:
            self.ser = serial.Serial(
                port=port,
                baudrate=NFC_BAUD_RATE,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1
            )

            if self._test_connection():
                return True
            else:
                self.ser.close()
                return False

        except (serial.SerialException, OSError) as e:
            logger.debug(f"Failed to connect to {port}: {e}")
            return False

    def _test_connection(self) -> bool:
        """Test device connection."""
        try:
            if self.ser and self.ser.is_open:
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
                return True
            return False
        except:
            return False

    def is_connected(self) -> bool:
        """Check if connected."""
        return self.ser is not None and self.ser.is_open

    def read_nfc_card(self) -> Optional[str]:
        """Read NFC card UID from serial device."""
        if not self.ser or not self.ser.is_open:
            return None

        try:
            # Command to read UID (ISO14443A)
            read_uid_command = bytes([
                0x0E, 0x01, 0x26, 0x01, 0x00, 0x01, 0x0A,
                0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xC4
            ])

            self.ser.reset_input_buffer()
            self.ser.write(read_uid_command)
            time.sleep(0.1)

            if self.ser.in_waiting > 0:
                response_len_byte = self.ser.read(1)

                if len(response_len_byte) > 0:
                    response_len = response_len_byte[0]

                    if 0 < response_len < 32:
                        remaining_bytes = self.ser.read(response_len - 1)
                        response = response_len_byte + remaining_bytes

                        if len(response) > 3:
                            status = response[3]

                            if status == 0x00 and response_len == 25:
                                uid = response[4:8]
                                uid_decimal = str(int.from_bytes(uid, byteorder='big'))
                                logger.info(f"NFC card detected (serial): {uid_decimal}")
                                return uid_decimal
            return None

        except Exception as e:
            logger.error(f"NFC read error: {e}")
            return None

    def read_qr_code(self) -> Optional[str]:
        """Read QR code from serial device."""
        try:
            if self.ser and self.ser.in_waiting > 0:
                qr_data = self.ser.readline().decode('utf-8', errors='ignore').strip()
                if qr_data and len(qr_data) > 0:
                    logger.info(f"QR code detected (serial): {qr_data}")
                    return qr_data
            return None
        except Exception as e:
            logger.error(f"QR read error: {e}")
            return None

    def read_card(self) -> Optional[Dict[str, str]]:
        """
        Unified card reading method with format detection.

        Returns:
            Dict with 'type' ('nfc' or 'qr') and 'data' keys,
            or None if no card read
        """
        if not self.ser or not self.ser.is_open:
            return None

        try:
            # First try reading as NFC (using command)
            nfc_uid = self.read_nfc_card()
            if nfc_uid:
                return {'type': 'nfc', 'data': nfc_uid}

            # Then try reading as QR (line-based)
            qr_data = self.read_qr_code()
            if qr_data:
                card_type = self._detect_card_type(qr_data)
                return {'type': card_type, 'data': qr_data}

            return None

        except Exception as e:
            logger.error(f"Card read error: {e}")
            return None

    @staticmethod
    def _detect_card_type(data: str) -> str:
        """
        Detect whether data is from NFC card or QR code.

        Returns:
            'nfc' or 'qr'
        """
        if not data:
            return 'qr'

        cleaned = data.strip().upper()

        # NFC UID patterns (typically 4-14 digit decimal, or hex)
        # Pattern 1: Pure numeric, 4-14 digits (typical card UID in decimal)
        if cleaned.isdigit() and 4 <= len(cleaned) <= 14:
            return 'nfc'

        # Pattern 2: Hex format with 8 chars (4-byte UID)
        if len(cleaned) == 8 and all(c in '0123456789ABCDEF' for c in cleaned):
            return 'nfc'

        # Pattern 3: Short alphanumeric (5-10 chars) - could be NFC or short QR
        # If it's mostly digits (>=70%), treat as NFC
        if 5 <= len(cleaned) <= 10:
            digit_count = sum(1 for c in cleaned if c.isdigit())
            if digit_count / len(cleaned) >= 0.7:
                return 'nfc'

        # Everything else is likely QR (longer, mixed alphanumeric, JSON fragments, etc.)
        return 'qr'

    @staticmethod
    def clean_hid_input(content: str) -> str:
        """
        Clean HID keyboard input by removing common noise patterns.

        HID readers often inject noise characters between keystrokes.
        """
        if not content:
            return ""

        # Remove common HID reader noise characters
        # 'M' is commonly inserted between keystrokes by some readers
        cleaned = content.strip()
        cleaned = cleaned.replace('M', '')

        # Remove other common noise patterns
        noise_chars = ['\x00', '\x01', '\x02', '\x03']
        for char in noise_chars:
            cleaned = cleaned.replace(char, '')

        return cleaned.strip()

    def close(self):
        """Close serial connection."""
        if self.ser and self.ser.is_open:
            self.ser.close()


class RFIDReader:
    """TCP-based RFID reader for inventory scanning."""

    def __init__(self, host: str = RFID_HOST, port: int = RFID_PORT):
        self.host = host
        self.port = port
        self.socket = None
        self.connected = False
        self.reading = False
        self.work_mode_tags = set()
        self.current_cycle = 0
        self.work_mode_cycles = RFID_READ_CYCLES
        self._recv_buffer = bytearray()
        self._idle_break_timeout = 0.2
        self._max_cycle_wait = 2.0

    def connect(self) -> bool:
        """Connect to RFID reader."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5)
            self.socket.connect((self.host, self.port))
            self.connected = True
            logger.info(f"RFID reader connected to {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"RFID connection failed: {e}")
            self.connected = False
            return False

    def _checksum(self, data: bytes) -> int:
        """Calculate checksum."""
        uSum = 0
        for byte in data:
            uSum = (uSum + (byte & 0xFF)) & 0xFF
        return ((~uSum) + 1) & 0xFF

    def _build_packet(self, cmd: int, data: bytes = b'') -> bytes:
        """Build protocol packet."""
        length = 1 + 1 + len(data) + 1
        packet_wo_checksum = bytes([0xA0, length & 0xFF, RFID_ADDRESS & 0xFF, cmd & 0xFF]) + data
        cs = self._checksum(packet_wo_checksum)
        return packet_wo_checksum + bytes([cs])

    def read_rfid_tags_multiple(self) -> List[str]:
        """Read RFID tags multiple times (work mode)."""
        if not self.connect():
            return []

        self.work_mode_tags.clear()
        self.current_cycle = 0
        self.reading = True

        logger.info(f"Starting RFID inventory - {self.work_mode_cycles} cycles")

        try:
            session = 0x01
            target = 0x00
            repeat = 0x01
            cmd_payload = bytes([session, target, repeat])

            while self.reading and self.current_cycle < self.work_mode_cycles:
                before_cycle = set(self.work_mode_tags)

                packet = self._build_packet(0x8B, cmd_payload)
                if self.socket:
                    self.socket.sendall(packet)

                self._receive_and_process()

                after_cycle = self.work_mode_tags
                new_tags = after_cycle - before_cycle

                if new_tags:
                    logger.debug(f"[Cycle {self.current_cycle+1}] New tags: {list(new_tags)}")

                self.current_cycle += 1
                time.sleep(RFID_READ_INTERVAL)

            tags_list = list(self.work_mode_tags)
            logger.info(f"RFID inventory completed: {len(tags_list)} tags found")
            return tags_list

        except Exception as e:
            logger.error(f"RFID read error: {e}")
            return []
        finally:
            self.stop_reading()
            self.disconnect()

    def read_rfid_tags_voting(
        self,
        total_cycles: int = 10,
        min_appearances: int = 3,
        read_interval: Optional[float] = None,
        idle_break_timeout: Optional[float] = None,
        max_cycle_wait: Optional[float] = None,
        log_each_cycle: bool = False,
    ) -> List[str]:
        """
        Read RFID tags with voting mechanism for better accuracy.

        A tag is considered present only if it appears in at least min_appearances
        out of total_cycles scans. This reduces false positives from sporadic reads.

        Args:
            total_cycles: Total number of scan cycles (default 10)
            min_appearances: Minimum times a tag must appear to be considered present (default 3)
            read_interval: Seconds between cycles (None uses hardware default)
            idle_break_timeout: Seconds of inactivity before a cycle ends
            max_cycle_wait: Max seconds to wait for data in one cycle
            log_each_cycle: Log tags found on each cycle

        Returns:
            List of tags that passed the voting threshold
        """
        from collections import Counter

        if not self.connect():
            return []

        # Clear any stale buffer data from a previous call
        self._recv_buffer.clear()

        tag_counter = Counter()
        cycle = 0
        self.reading = True

        interval = RFID_READ_INTERVAL if read_interval is None else read_interval
        prev_idle = self._idle_break_timeout
        prev_max_wait = self._max_cycle_wait
        if idle_break_timeout is not None:
            self._idle_break_timeout = idle_break_timeout
        if max_cycle_wait is not None:
            self._max_cycle_wait = max_cycle_wait

        logger.info(
            "Starting RFID voting scan - %s cycles, need %s appearances (interval=%.2fs, idle=%.2fs, max_wait=%.2fs)",
            total_cycles,
            min_appearances,
            interval,
            self._idle_break_timeout,
            self._max_cycle_wait,
        )

        try:
            session = 0x01
            target = 0x00
            repeat = 0x01

            while self.reading and cycle < total_cycles:
                # Toggle target between 0x00 and 0x01 every cycle to capture inverted tags (Session 1)
                target = 0x00 if cycle % 2 == 0 else 0x01
                cmd_payload = bytes([session, target, repeat])

                # Clear tags for this cycle to get fresh detection
                self.work_mode_tags.clear()

                packet = self._build_packet(0x8B, cmd_payload)
                if self.socket:
                    self.socket.sendall(packet)

                # Receive for this cycle
                self._receive_and_process()
                cycle_tags = set(self.work_mode_tags)

                # Count each tag found in this cycle
                for tag in cycle_tags:
                    tag_counter[tag] += 1

                if log_each_cycle:
                    logger.info(
                        "[RFID] Cycle %s/%s -> %s",
                        cycle + 1,
                        total_cycles,
                        sorted(cycle_tags),
                    )
                else:
                    logger.debug(f"[Cycle {cycle+1}/{total_cycles}] Found: {list(cycle_tags)}")
                cycle += 1
                time.sleep(interval)

            # Apply voting threshold - tag must appear at least min_appearances times
            confirmed_tags = [tag for tag, count in tag_counter.items() if count >= min_appearances]

            logger.info(f"RFID voting completed: {len(confirmed_tags)} confirmed tags (from {len(tag_counter)} unique)")
            logger.info(f"Tag appearances: {dict(tag_counter)}")
            logger.info(f"Confirmed tags: {confirmed_tags}")

            return confirmed_tags

        except Exception as e:
            logger.error(f"RFID voting read error: {e}")
            return []
        finally:
            self._idle_break_timeout = prev_idle
            self._max_cycle_wait = prev_max_wait
            self.stop_reading()
            self.disconnect()

    def _receive_and_process(self):
        """Receive and process RFID data."""
        start_time = time.time()
        last_data_time = time.time()
        bytes_received = 0

        while self.reading and (time.time() - start_time) < self._max_cycle_wait:
            try:
                self.socket.settimeout(0.1)
                data = self.socket.recv(4096)
                if data:
                    last_data_time = time.time()
                    bytes_received += len(data)
                    self._recv_buffer.extend(data)
                    frames_found = self._extract_frames_from_buffer()
                    logger.debug(f"RFID recv: {len(data)} bytes, frames found: {frames_found}")
                else:
                    # No data received, check idle timeout
                    if (time.time() - last_data_time) > self._idle_break_timeout:
                        logger.debug(f"RFID idle timeout after {bytes_received} bytes")
                        break
            except socket.timeout:
                if (time.time() - last_data_time) > self._idle_break_timeout:
                    logger.debug(f"RFID idle timeout (socket) after {bytes_received} bytes")
                    break
                continue
            except Exception as e:
                logger.error(f"RFID receive error: {e}")
                break

        if bytes_received > 0:
            logger.debug(f"RFID receive cycle complete: {bytes_received} bytes, buffer remaining: {len(self._recv_buffer)}")

    def _extract_frames_from_buffer(self) -> int:
        """
        Extract frames from receive buffer.

        Returns:
            Number of valid frames extracted
        """
        buf = self._recv_buffer
        pos = 0
        frames_found = 0
        MAX_FRAME_LEN = 256  # Maximum reasonable frame length

        while pos + 5 <= len(buf):
            # Look for frame header 0xA0
            if buf[pos] != 0xA0:
                pos += 1
                continue

            # Check if we have enough bytes for length field
            if pos + 2 > len(buf):
                break

            length = buf[pos + 1]
            frame_total_len = 2 + length

            # Sanity check: frame length should be reasonable
            if length < 3 or frame_total_len > MAX_FRAME_LEN:
                # Invalid length, skip this potential header and continue searching
                logger.debug(f"Invalid frame length {length} at pos {pos}, skipping")
                pos += 1
                continue

            # Check if we have the complete frame
            if pos + frame_total_len > len(buf):
                # Incomplete frame, keep buffer for next receive
                logger.debug(f"Incomplete frame: need {frame_total_len}, have {len(buf) - pos}")
                break

            # Extract and validate frame
            frame = bytes(buf[pos: pos + frame_total_len])
            received_cs = frame[-1]
            calc_cs = self._checksum(frame[:-1])

            if received_cs != calc_cs:
                logger.debug(f"Checksum mismatch at pos {pos}: received {received_cs:02X}, calc {calc_cs:02X}")
                # Try to find next frame header within this failed frame
                next_a0 = self._find_next_header(buf, pos + 1, pos + frame_total_len)
                if next_a0 > 0:
                    pos = next_a0
                else:
                    pos += 1
                continue

            # Valid frame found, parse it
            try:
                self._parse_frame(frame)
                frames_found += 1
            except Exception as e:
                logger.warning(f"Frame parse error: {e}, frame: {frame.hex()}")

            pos += frame_total_len

        # Keep unprocessed bytes in buffer
        if pos > 0:
            remaining = buf[pos:]
            self._recv_buffer = bytearray(remaining)
            if pos > 0 and len(remaining) > 0:
                logger.debug(f"Buffer advanced by {pos}, {len(remaining)} bytes remaining")

        return frames_found

    def _find_next_header(self, buf: bytearray, start: int, end: int) -> int:
        """Find next 0xA0 header in buffer range."""
        for i in range(start, min(end, len(buf))):
            if buf[i] == 0xA0:
                return i
        return -1

    def _parse_frame(self, frame: bytes):
        """Parse a single frame."""
        if len(frame) < 5:
            logger.debug(f"Frame too short: {len(frame)} bytes")
            return

        length = frame[1]
        addr = frame[2]
        cmd = frame[3]
        data_len = max(0, length - 3)

        # Validate frame structure
        expected_len = 2 + length
        if len(frame) != expected_len:
            logger.debug(f"Frame length mismatch: expected {expected_len}, got {len(frame)}")
            return

        data = frame[4:4 + data_len] if data_len > 0 else b''

        logger.debug(f"Parsing frame: addr=0x{addr:02X}, cmd=0x{cmd:02X}, data_len={data_len}")

        if cmd == 0x8B:
            self._parse_tag_data_bytes(data)
        elif cmd == 0x8A:
            logger.debug("Received inventory stop response")
        else:
            logger.debug(f"Unknown command: 0x{cmd:02X}")

    def _parse_tag_data_bytes(self, data: bytes):
        """
        Parse tag data from frame.

        Frame format (per tag):
        - freq_ant (1 byte): frequency and antenna info
        - PC (2 bytes): Protocol Control word
        - EPC (variable): Electronic Product Code
        - RSSI (1 byte): Signal strength
        """
        pos = 0
        tag_count = 0

        while pos < len(data):
            # Need at least: freq_ant (1) + PC (2) + minimal EPC (2) + RSSI (1) = 6 bytes
            if pos + 6 > len(data):
                logger.debug(f"Insufficient data for tag at pos {pos}: {len(data) - pos} bytes remaining")
                break

            freq_ant = data[pos]
            pos += 1
            antenna = (freq_ant & 0x03) + 1

            # Parse PC (Protocol Control)
            if pos + 2 > len(data):
                logger.debug(f"Insufficient data for PC at pos {pos}")
                break

            pc_byte1 = data[pos]
            pc_byte2 = data[pos + 1]
            pos += 2
            pc_value = (pc_byte1 << 8) | pc_byte2

            # EPC length from PC: bits 10-14 (number of 16-bit words)
            epc_word_len = (pc_value >> 11) & 0x1F
            epc_byte_len = epc_word_len * 2

            # Validate EPC length
            if epc_byte_len < 2 or epc_byte_len > 62:  # Reasonable EPC length range
                logger.debug(f"Invalid EPC length from PC: {epc_word_len} words ({epc_byte_len} bytes)")
                # Try to continue parsing from next byte
                pos -= 2  # Back up to re-sync
                pos += 1
                continue

            # Check if we have enough data for EPC + RSSI
            if pos + epc_byte_len + 1 > len(data):
                logger.debug(f"Insufficient data for EPC at pos {pos}: need {epc_byte_len + 1}, have {len(data) - pos}")
                break

            epc_data = data[pos: pos + epc_byte_len]
            pos += epc_byte_len

            rssi_byte = data[pos]
            pos += 1

            # Convert to hex and validate
            epc_hex = epc_data.hex().upper()
            rssi_dbm = self._rssi_to_dbm(rssi_byte)

            if self._validate_epc(epc_hex) and epc_hex not in IGNORED_TAGS:
                self.work_mode_tags.add(epc_hex)
                tag_count += 1
                logger.debug(f"Tag found: EPC={epc_hex}, Ant={antenna}, RSSI={rssi_dbm}dBm")
            else:
                logger.debug(f"Invalid or ignored tag: {epc_hex}")

        if tag_count > 0:
            logger.debug(f"Parsed {tag_count} tags from frame")

    def _rssi_to_dbm(self, rssi_byte: int) -> int:
        """Convert RSSI byte to dBm value."""
        # RSSI is typically represented as a signed value
        if rssi_byte > 127:
            return rssi_byte - 256
        return rssi_byte

    def _validate_epc(self, epc_hex: str) -> bool:
        """Validate EPC data."""
        if not epc_hex:
            return False
        if len(epc_hex) % 2 != 0 or len(epc_hex) < 4 or len(epc_hex) > 62:
            return False
        try:
            bytes.fromhex(epc_hex)
            return True
        except:
            return False

    def stop_reading(self):
        """Stop reading."""
        self.reading = False

    def disconnect(self):
        """Disconnect from reader."""
        self.stop_reading()
        try:
            if self.socket:
                self.socket.close()
        except:
            pass
        self.socket = None
        self.connected = False


class RaspberryPiHardware(HardwareInterface):
    """Raspberry Pi hardware implementation."""

    def __init__(self, num_drawers: int = 4, num_leds: int = 8, nfc_mode: str = "auto"):
        self.num_drawers = num_drawers
        self.num_leds = num_leds
        self._initialized = False
        self._drawer_states = {i: DrawerState.CLOSED for i in range(num_drawers)}
        self._nfc_reader = None
        self._rfid_reader = None
        self._hid_reader = None
        self._nfc_mode = nfc_mode
        self._strip = None
        # Cache for cross-read data (when NFC is read during QR read or vice versa)
        self._last_read_data = None
        self._last_read_type = None

    def initialize(self) -> None:
        """Initialize hardware components."""
        if not RPI_AVAILABLE:
            logger.warning("RPi libraries not available - running in simulation mode")
            self._initialized = True
            return

        # Initialize GPIO
        GPIO.setmode(GPIO.BCM)

        # Setup solenoid pins
        for pin in SOLENOID_PINS:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW) # Ensure locked on start

        # Setup drawer switch pins (internal pull-down: HIGH = drawer open)
        for pin in DRAWER_SWITCH_PINS:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

        # Initialize WS2812B Strip
        try:
            self._strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
            self._strip.begin()
            logger.info("WS2812B Strip initialized")
        except Exception as e:
            logger.error(f"Failed to initialize WS2812B strip: {e}")

        # Initialize NFC/QR reader
        self._init_nfc_reader()

        # Initialize RFID reader
        try:
            self._rfid_reader = RFIDReader()
        except Exception as e:
            logger.error(f"Failed to initialize RFID reader: {e}")

        self._initialized = True
        logger.info("Raspberry Pi hardware initialized (Solenoids + WS2812B)")

    def _init_nfc_reader(self):
        """Initialize NFC reader - tries serial first, then HID keyboard."""
        if self._nfc_mode == "none":
            logger.info("NFC reader disabled")
            return

        # Try serial reader first
        if self._nfc_mode in ("auto", "serial"):
            try:
                self._nfc_reader = NFCQRReader()
                if self._nfc_reader._test_connection():
                    logger.info("Serial NFC reader initialized")
                    return
            except Exception as e:
                logger.debug(f"Serial NFC reader not available: {e}")

        # Try HID keyboard reader
        if self._nfc_mode in ("auto", "hid"):
            try:
                from .hid_keyboard_reader import HIDKeyboardReader
                self._hid_reader = HIDKeyboardReader()
                if self._hid_reader.is_available():
                    logger.info("HID keyboard NFC reader initialized")
                    return
            except Exception as e:
                logger.debug(f"HID keyboard reader not available: {e}")

        logger.warning("No NFC reader available")

    def read_nfc(self, timeout: float = 30.0) -> Optional[str]:
        """Read NFC card UID."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Try HID reader first (most common in production)
            if self._hid_reader and self._hid_reader.is_available():
                raw = self._hid_reader.read_card(timeout=min(1.0, timeout - (time.time() - start_time)))
                if raw:
                    # Clean and detect type
                    cleaned = NFCQRReader.clean_hid_input(raw)
                    card_type = NFCQRReader._detect_card_type(cleaned)

                    if card_type == 'nfc':
                        logger.info(f"NFC card detected (HID): {cleaned}")
                        return cleaned
                    else:
                        logger.debug(f"QR code detected but read_nfc called: {cleaned[:20]}...")
                        # Store for potential QR read
                        self._last_read_data = cleaned
                        self._last_read_type = 'qr'
                continue

            # Try serial reader
            if self._nfc_reader and self._nfc_reader.is_connected():
                result = self._nfc_reader.read_card()
                if result:
                    if result['type'] == 'nfc':
                        return result['data']
                    else:
                        # Store for QR read
                        self._last_read_data = result['data']
                        self._last_read_type = 'qr'

            time.sleep(0.1)

        return None

    def read_qr(self, timeout: float = 30.0) -> Optional[str]:
        """Read QR code."""
        start_time = time.time()

        # Check if we have cached QR data from previous read
        if hasattr(self, '_last_read_data') and getattr(self, '_last_read_type', None) == 'qr':
            data = self._last_read_data
            self._last_read_data = None
            self._last_read_type = None
            logger.info(f"QR code returned from cache: {data[:30]}...")
            return data

        while time.time() - start_time < timeout:
            # Try HID reader first
            if self._hid_reader and self._hid_reader.is_available():
                raw = self._hid_reader.read_card(timeout=min(1.0, timeout - (time.time() - start_time)))
                if raw:
                    # Clean and detect type
                    cleaned = NFCQRReader.clean_hid_input(raw)
                    card_type = NFCQRReader._detect_card_type(cleaned)

                    if card_type == 'qr':
                        logger.info(f"QR code detected (HID): {cleaned[:30]}...")
                        return cleaned
                    else:
                        logger.debug(f"NFC card detected but read_qr called: {cleaned}")
                        # Store for potential NFC read
                        self._last_read_data = cleaned
                        self._last_read_type = 'nfc'
                continue

            # Try serial reader
            if self._nfc_reader and self._nfc_reader.is_connected():
                result = self._nfc_reader.read_card()
                if result:
                    if result['type'] == 'qr':
                        return result['data']
                    else:
                        # Store for NFC read
                        self._last_read_data = result['data']
                        self._last_read_type = 'nfc'

            time.sleep(0.1)

        return None

    def read_card_auto(self, timeout: float = 30.0) -> Optional[Dict[str, str]]:
        """
        Read card and automatically detect type (NFC or QR).

        Returns:
            Dict with 'type' ('nfc' or 'qr') and 'data' keys,
            or None if timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Try HID reader first
            if self._hid_reader and self._hid_reader.is_available():
                raw = self._hid_reader.read_card(timeout=min(1.0, timeout - (time.time() - start_time)))
                if raw:
                    cleaned = NFCQRReader.clean_hid_input(raw)
                    card_type = NFCQRReader._detect_card_type(cleaned)
                    logger.info(f"Card detected (HID): type={card_type}, data={cleaned[:30]}...")
                    return {'type': card_type, 'data': cleaned}
                continue

            # Try serial reader
            if self._nfc_reader and self._nfc_reader.is_connected():
                result = self._nfc_reader.read_card()
                if result:
                    return result

            time.sleep(0.1)

        return None

    def read_rfid_tags(self, drawer_id: Optional[int] = None) -> List[str]:
        """Read RFID tags."""
        if not self._rfid_reader:
            return []

        return self._rfid_reader.read_rfid_tags_multiple()

    def read_rfid_tags_voting(
        self,
        total_cycles: int = 10,
        min_appearances: int = 3,
        read_interval: Optional[float] = None,
        idle_break_timeout: Optional[float] = None,
        max_cycle_wait: Optional[float] = None,
        log_each_cycle: bool = False,
    ) -> List[str]:
        """
        Read RFID tags with voting mechanism for better accuracy.

        A tag is considered present only if it appears in at least min_appearances
        out of total_cycles scans. This reduces false positives from sporadic reads.

        Args:
            total_cycles: Total number of scan cycles (default 10)
            min_appearances: Minimum times a tag must appear to be considered present (default 3)

        Returns:
            List of tags that passed the voting threshold
        """
        if not self._rfid_reader:
            return []

        return self._rfid_reader.read_rfid_tags_voting(
            total_cycles=total_cycles,
            min_appearances=min_appearances,
            read_interval=read_interval,
            idle_break_timeout=idle_break_timeout,
            max_cycle_wait=max_cycle_wait,
            log_each_cycle=log_each_cycle,
        )

    def unlock_drawer(self, drawer_id: int) -> bool:
        """Unlock a specific solenoid."""
        if drawer_id < 0 or drawer_id >= len(SOLENOID_PINS):
            return False

        try:
            pin = SOLENOID_PINS[drawer_id]
            GPIO.output(pin, GPIO.HIGH) # Energize solenoid
            self._drawer_states[drawer_id] = DrawerState.OPEN
            logger.info(f"Solenoid {drawer_id} (GPIO {pin}) energized (unlocked)")
            return True
        except Exception as e:
            logger.error(f"Failed to unlock drawer {drawer_id}: {e}")
            return False

    def lock_drawer(self, drawer_id: int) -> bool:
        """Lock a specific solenoid."""
        if drawer_id < 0 or drawer_id >= len(SOLENOID_PINS):
            return False

        try:
            pin = SOLENOID_PINS[drawer_id]
            GPIO.output(pin, GPIO.LOW) # De-energize solenoid
            self._drawer_states[drawer_id] = DrawerState.CLOSED
            logger.info(f"Solenoid {drawer_id} (GPIO {pin}) de-energized (locked)")
            return True
        except Exception as e:
            logger.error(f"Failed to lock drawer {drawer_id}: {e}")
            return False

    def unlock_all(self) -> bool:
        """Unlock all solenoids."""
        try:
            for i in range(self.num_drawers):
                self.unlock_drawer(i)
            return True
        except Exception as e:
            logger.error(f"Failed to unlock all drawers: {e}")
            return False

    def lock_all(self) -> bool:
        """Lock all solenoids."""
        try:
            for i in range(self.num_drawers):
                self.lock_drawer(i)
            return True
        except Exception as e:
            logger.error(f"Failed to lock all drawers: {e}")
            return False

    def get_drawer_state(self, drawer_id: int) -> DrawerState:
        """Get drawer state from switch."""
        if not RPI_AVAILABLE or drawer_id < 0 or drawer_id >= len(DRAWER_SWITCH_PINS):
            return self._drawer_states.get(drawer_id, DrawerState.UNKNOWN)

        try:
            pin = DRAWER_SWITCH_PINS[drawer_id]
            # HIGH means open (switch not pressed, pulled up externally)
            if GPIO.input(pin) == GPIO.HIGH:
                return DrawerState.OPEN
            else:
                return DrawerState.CLOSED
        except Exception as e:
            logger.error(f"Failed to read drawer {drawer_id} state: {e}")
            return DrawerState.UNKNOWN

    def are_all_drawers_closed(self) -> bool:
        """Check if all drawers are closed."""
        if not RPI_AVAILABLE:
            return all(s == DrawerState.CLOSED for s in self._drawer_states.values())

        try:
            for pin in DRAWER_SWITCH_PINS[:self.num_drawers]:
                if GPIO.input(pin) == GPIO.HIGH:
                    return False
            return True
        except Exception as e:
            logger.error(f"Failed to check drawer states: {e}")
            return False

    @staticmethod
    def _to_ws_color(color) -> 'Color':
        """Accept LEDColor enum or plain string and return rpi_ws281x Color."""
        name = color.value if isinstance(color, LEDColor) else str(color).lower()
        return {
            'red':    Color(255, 0, 0),
            'green':  Color(0, 255, 0),
            'yellow': Color(255, 255, 0),
            'blue':   Color(0, 0, 255),
            'white':  Color(255, 255, 255),
        }.get(name, Color(0, 0, 0))

    def set_led(self, index: int, color, brightness: float = 1.0) -> None:
        """Set WS2812B LED color."""
        if not self._strip or index < 0 or index >= LED_COUNT:
            return
        try:
            self._strip.setPixelColor(index, self._to_ws_color(color))
            self._strip.show()
        except Exception as e:
            logger.error(f"Failed to set WS2812B LED {index}: {e}")

    def set_all_leds(self, color, brightness: float = 1.0) -> None:
        """Set all WS2812B LEDs to same color."""
        if not self._strip:
            return
        ws_color = self._to_ws_color(color)
        for i in range(LED_COUNT):
            self._strip.setPixelColor(i, ws_color)
        self._strip.show()

    def cleanup(self) -> None:
        """Cleanup resources."""
        logger.info("Starting hardware cleanup...")

        # Lock all drawers first (ensure solenoids are de-energized)
        self.lock_all()

        # Close readers
        if self._nfc_reader:
            self._nfc_reader.close()

        if self._rfid_reader:
            self._rfid_reader.disconnect()

        # Turn off LEDs and give time for signal to propagate
        if self._strip:
            self.set_all_leds(LEDColor.OFF)
            time.sleep(0.1)  # Allow LED strip to update

        # Clean up GPIO
        if RPI_AVAILABLE:
            GPIO.cleanup()

        self._initialized = False
        logger.info("Hardware cleanup complete")


    def health_check(self) -> Dict[str, Any]:
        """Check hardware health."""
        return {
            "status": "healthy" if self._initialized else "not_initialized",
            "mode": "raspberry_pi",
            "rpi_available": RPI_AVAILABLE,
            "solenoids": "ok" if self._initialized else "error",
            "nfc": "ok" if self._nfc_reader and self._nfc_reader._test_connection() else ("ok" if self._hid_reader and self._hid_reader.is_available() else "error"),
            "rfid": "ok" if self._rfid_reader else "error",
            "drawers": self.num_drawers,
            "leds": self.num_leds,
        }

    def get_all_drawer_states(self) -> Dict[int, DrawerState]:
        """Get states of all drawers."""
        return {i: self.get_drawer_state(i) for i in range(self.num_drawers)}

    def led_pattern(self, pattern: str, color: LEDColor, duration: float = 1.0) -> None:
        """Run an LED pattern."""
        import time as time_module

        if not self._strip:
            return

        if pattern == "blink":
            self._led_blink(color, duration)
        elif pattern == "chase":
            self._led_chase(color, duration)
        elif pattern == "rainbow":
            self.rainbow_breath()
        else:
            logger.warning(f"Unknown LED pattern: {pattern}")

    def _led_blink(self, color: LEDColor, duration: float):
        """Blink the LEDs."""
        end_time = time.time() + duration
        while time.time() < end_time:
            self.set_all_leds(color)
            time.sleep(0.25)
            self.set_all_leds(LEDColor.OFF)
            time.sleep(0.25)

    def _led_chase(self, color: LEDColor, duration: float):
        """Chase the LEDs."""
        end_time = time.time() + duration
        step_delay = max(0.005, duration / max(1, LED_COUNT))  # fit full loop in requested duration
        while time.time() < end_time:
            for i in range(LED_COUNT):
                self.set_led(i, color)
                time.sleep(step_delay)
                self.set_led(i, LEDColor.OFF)
        return

    @staticmethod
    def wheel(pos: int):
        """Color helper for rainbow patterns (0-255)."""
        pos = max(0, min(255, pos))

        if pos < 85:
            return Color(pos * 3, 255 - pos * 3, 0)
        if pos < 170:
            pos -= 85
            return Color(255 - pos * 3, 0, pos * 3)

        pos -= 170
        return Color(0, pos * 3, 255 - pos * 3)

    def rainbow_cycle(self, wait_ms=20, iterations=5):
        """Draw rainbow that fades across all pixels at once."""
        if not self._strip:
            return

        delay = max(0.005, wait_ms / 1000.0)
        for j in range(256 * iterations):
            for i in range(self._strip.numPixels()):
                self._strip.setPixelColor(i, self.wheel((i + j) & 255))
            self._strip.show()
            time.sleep(delay)

    def rainbow_breath(self, wait_ms=12, iterations=5, brightness_steps=45):
        """Rainbow colors at constant brightness (no breathing)."""
        if not self._strip:
            return

        # Keep a steady brightness and reuse the existing rainbow cycle
        self._strip.setBrightness(LED_BRIGHTNESS)
        for _ in range(iterations):
            self.rainbow_cycle(wait_ms=wait_ms, iterations=1)

    def beep(self, duration: float = 0.1, frequency: Optional[int] = None) -> None:
        """Play a beep sound (no buzzer hardware - no-op)."""
        # No buzzer on current hardware
        logger.debug(f"Beep: duration={duration}s, frequency={frequency}Hz (no hardware)")

    def beep_success(self) -> None:
        """Play success beep pattern."""
        self.beep(0.1)

    def beep_error(self) -> None:
        """Play error beep pattern."""
        self.beep(0.1)
        time.sleep(0.05)
        self.beep(0.1)

    def beep_warning(self) -> None:
        """Play warning beep pattern."""
        self.beep(0.3)
