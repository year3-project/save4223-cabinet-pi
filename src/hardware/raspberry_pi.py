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
from .hidraw_reader import HIDRawReader

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
IGNORED_TAGS = {"00B07A15306008EFF68E8F54", "0000"}

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
        Uses regex to keep only alphanumeric characters.
        """
        import re
        if not content:
            return ""
        # Keep only letters and digits, discard all noise like 'M' or control chars
        return re.sub(r'[^a-zA-Z0-9]', '', content)

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
        self._idle_break_timeout = 2.0
        self._max_cycle_wait = 2.0
        self._tag_callback = None  # Optional callback for tag detection

    def connect(self) -> bool:
        """Connect to RFID reader with antenna and power initialization."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5)
            self.socket.connect((self.host, self.port))
            self.connected = True
            logger.info(f"RFID reader connected to {self.host}:{self.port}")

            # Initialize antenna and power for optimal reading
            self._init_reader()

            return True
        except Exception as e:
            logger.error(f"RFID connection failed: {e}")
            self.connected = False
            return False

    def _init_reader(self):
        """Initialize reader settings for optimal tag detection."""
        try:
            # Set output power to 33dBm (0x21) per protocol manual
            self._set_output_power(0x21)
            time.sleep(0.05)

            logger.debug("RFID reader initialized (power=33dBm)")
        except Exception as e:
            logger.warning(f"RFID initialization warning: {e}")

    def _set_antenna(self, ant_id: int):
        """Select active antenna on the RFID reader.

        Args:
            ant_id: Antenna number (0x00=antenna 1, 0x01=antenna 2, 0xFF=all)
        """
        try:
            packet = self._build_packet(0x74, bytes([ant_id & 0xFF]))
            if self.socket:
                self.socket.sendall(packet)
                time.sleep(0.05)
                # Read and discard response
                self.socket.settimeout(0.3)
                try:
                    self.socket.recv(256)
                except socket.timeout:
                    pass
            logger.debug(f"RFID antenna set to {ant_id} (0x{ant_id:02X})")
        except Exception as e:
            logger.warning(f"Failed to set antenna {ant_id}: {e}")

    def _checksum(self, data: bytes) -> int:
        """Calculate checksum per ZTX-RM702 manual: sum from Len byte, exclude 0xA0 header."""
        total = sum(b & 0xFF for b in data) & 0xFF
        return ((~total) + 1) & 0xFF

    def _build_packet(self, cmd: int, data: bytes = b'') -> bytes:
        """Build protocol packet (compatible with master branch).

        Frame format: [0xA0][Len][Addr][Cmd][Data...][Checksum]
        - Len: Count of bytes AFTER Len (Addr + Cmd + Data + Checksum) = len(data) + 3
        - Checksum: Hardware requires including 0xA0 header in calculation
        """
        length = len(data) + 3  # Addr(1) + Cmd(1) + Data(N) + Check(1)
        # Build packet WITH 0xA0 for checksum calculation (master branch compatible)
        packet_wo_checksum = bytes([0xA0, length & 0xFF, RFID_ADDRESS & 0xFF, cmd & 0xFF]) + data
        cs = self._checksum(packet_wo_checksum)  # Include 0xA0
        return packet_wo_checksum + bytes([cs])

    def _set_output_power(self, power_dbm: int = 0x1A) -> bool:
        """
        Set RFID reader output power.

        Args:
            power_dbm: Power level in dBm (0x00-0x1E, max 30dBm)
                       Recommended: 0x1A (26dBm) for 1m³ metal cabinet

        Returns:
            True if command was sent successfully
        """
        try:
            # Command 0x76 = Set Output Power
            # Data: [Power]
            packet = self._build_packet(0x76, bytes([power_dbm & 0xFF]))
            if self.socket:
                self.socket.sendall(packet)
                # Wait briefly for response
                time.sleep(0.1)
                # Read and discard response
                self.socket.settimeout(0.5)
                try:
                    self.socket.recv(256)
                except socket.timeout:
                    pass
                logger.info(f"RFID output power set to {power_dbm}dBm (0x{power_dbm:02X})")
                return True
        except Exception as e:
            logger.warning(f"Failed to set RFID power: {e}")
        return False

    def read_rfid_tags_multiple(self) -> List[str]:
        """
        Read RFID tags multiple times (work mode).

        Delegates to continuous scan to avoid command flooding issues.
        """
        scan_duration = self.work_mode_cycles * RFID_READ_INTERVAL
        logger.info(f"Starting RFID inventory - {scan_duration:.1f}s continuous scan")
        result = self.read_rfid_tags_continuous(scan_duration=scan_duration)
        return result['tags']

    def read_rfid_tags_inventory(
        self,
        scan_passes: int = 3,
        pass_duration: float = 5.0,
        cooldown: float = 0.3,
        antennas: Optional[List[int]] = None,
    ) -> List[str]:
        """
        Inventory-optimized RFID scan with multi-antenna support.

        Uses the 0x8A fast-switch-antenna inventory command when multiple
        antennas are configured.  Falls back to standard 0x8B for single
        antenna setups.

        Args:
            scan_passes: Number of scan passes (default 3).
                         With dual antennas each pass covers both antennas.
            pass_duration: Duration of each pass in seconds (default 5.0).
            cooldown: Delay between passes in seconds (default 0.3).
            antennas: List of antenna IDs (e.g. [0, 1]).
                      None or [0] uses single-antenna 0x8B mode.

        Returns:
            List of unique tags detected across all passes (sorted by freq)
        """
        from collections import Counter

        if not antennas:
            antennas = [0x00]

        multi_ant = len(antennas) > 1
        all_tags = set()
        tag_counter = Counter()
        pass_details = []

        if multi_ant:
            logger.info(
                f"Starting fast-switch inventory: {scan_passes} passes x "
                f"{pass_duration}s, antennas={[f'0x{a:02X}' for a in antennas]}"
            )
        else:
            logger.info(
                f"Starting inventory scan: {scan_passes} passes x {pass_duration}s"
            )

        for pass_num in range(scan_passes):
            if multi_ant:
                result = self._fast_switch_ant_scan(
                    antennas=antennas,
                    scan_duration=pass_duration,
                )
            else:
                result = self.read_rfid_tags_continuous(
                    scan_duration=pass_duration,
                    toggle_target=True,
                    idle_break_timeout=0.3,
                )

            pass_tags = set(result['tags'])
            all_tags.update(pass_tags)
            tag_counter.update(result['tag_count'])
            pass_details.append(len(pass_tags))

            logger.info(
                f"Pass {pass_num + 1}/{scan_passes}: {len(pass_tags)} tags "
                f"(cumulative: {len(all_tags)})"
            )

            if pass_num < scan_passes - 1:
                time.sleep(cooldown)

        # Sort by detection frequency (most reliable first)
        sorted_tags = sorted(
            all_tags,
            key=lambda t: tag_counter[t],
            reverse=True
        )

        logger.info(
            f"Inventory complete: {len(sorted_tags)} unique tags from "
            f"{scan_passes} passes {pass_details}"
        )
        logger.info(f"Tag detection counts: {dict(tag_counter)}")

        return sorted_tags

    def _fast_switch_ant_scan(
        self,
        antennas: List[int],
        scan_duration: float = 8.0,
        ant_repeat: int = 3,
        rest_time: int = 0,
    ) -> Dict[str, Any]:
        """
        Fast-switch antenna inventory using command 0x8A (protocol V4.1.7).

        Sends a single command that tells the reader to poll the specified
        antennas in sequence.  The reader handles antenna switching internally.

        Packet format for cmd 0x8A:
            [ant_A_id] [ant_A_repeat] [ant_B_id] [ant_B_repeat]
            [ant_C_id] [ant_C_repeat] [ant_D_id] [ant_D_repeat]
            [rest_time_ms] [loop_count]

        Antenna ID 0x04 = skip (don't poll that slot).

        Args:
            antennas: List of antenna IDs to poll (e.g. [0, 1])
            scan_duration: Approximate total scan time in seconds
            ant_repeat: Number of inventory rounds per antenna per loop (default 3)
            rest_time: Milliseconds between antenna switches (default 0)

        Returns:
            Dict with 'tags', 'tag_count', etc.
        """
        from collections import defaultdict

        tag_count: Dict[str, int] = defaultdict(int)
        bytes_received = 0
        frames_parsed = 0
        self.work_mode_tags.clear()
        self._recv_buffer.clear()

        # Loop count: test results show repeat=1, loops=10-20 is the sweet spot
        # for dual-antenna setups. More rounds don't improve detection.
        est_time_per_loop = len(antennas) * ant_repeat * 0.3
        loop_count = max(10, int(scan_duration / max(est_time_per_loop, 0.1)))
        loop_count = min(loop_count, 0xFF)  # Protocol limit: 1 byte

        # Build antenna config (4 slots, unused = 0x04)
        ant_slots = list(antennas[:4])
        while len(ant_slots) < 4:
            ant_slots.append(0x04)  # skip

        data = bytes([
            ant_slots[0], ant_repeat,
            ant_slots[1], ant_repeat,
            ant_slots[2], ant_repeat,
            ant_slots[3], ant_repeat,
            rest_time & 0xFF,
            loop_count & 0xFF,
        ])

        if not self.connect():
            return {'tags': [], 'tag_count': {}, 'bytes_received': 0, 'frames_parsed': 0}

        try:
            packet = self._build_packet(0x8A, data)
            logger.info(
                f"Sending fast-switch cmd 0x8A: antennas={antennas}, "
                f"repeat={ant_repeat}, loops={loop_count}, "
                f"data={data.hex()}"
            )
            self.socket.sendall(packet)

            # Collect responses for the expected duration
            start_time = time.time()
            last_data_time = start_time

            while (time.time() - start_time) < scan_duration + 2.0:
                try:
                    self.socket.settimeout(0.5)
                    recv_data = self.socket.recv(4096)
                    if recv_data:
                        last_data_time = time.time()
                        bytes_received += len(recv_data)
                        self._recv_buffer.extend(recv_data)
                        frames_parsed += self._extract_frames_from_buffer()

                        # Accumulate tags found so far
                        cycle_tags = set(self.work_mode_tags)
                        for tag in cycle_tags:
                            tag_count[tag] += 1
                        self.work_mode_tags.clear()
                    else:
                        if (time.time() - last_data_time) > 2.0:
                            break
                except socket.timeout:
                    if (time.time() - last_data_time) > 2.0:
                        break
                    continue
                except Exception as e:
                    logger.error(f"Fast-switch receive error: {e}")
                    break

            # Process any remaining buffer
            if self._recv_buffer:
                frames_parsed += self._extract_frames_from_buffer()
                for tag in self.work_mode_tags:
                    tag_count[tag] += 1

            detected_tags = list(tag_count.keys())
            logger.info(
                f"Fast-switch scan complete: {len(detected_tags)} tags, "
                f"{bytes_received} bytes, {frames_parsed} frames"
            )

            return {
                'tags': detected_tags,
                'tag_count': dict(tag_count),
                'bytes_received': bytes_received,
                'frames_parsed': frames_parsed,
            }

        except Exception as e:
            logger.error(f"Fast-switch scan error: {e}")
            return {
                'tags': list(tag_count.keys()),
                'tag_count': dict(tag_count),
                'bytes_received': bytes_received,
                'frames_parsed': frames_parsed,
            }
        finally:
            self.disconnect()

    def read_rfid_tags_voting(
        self,
        total_cycles: int = 10,
        min_appearances: int = 3,
        read_interval: Optional[float] = None,
        idle_break_timeout: Optional[float] = None,
        max_cycle_wait: Optional[float] = None,
        log_each_cycle: bool = False,
        scan_duration: Optional[float] = None,
    ) -> List[str]:
        """
        Read RFID tags with voting mechanism for better accuracy.

        NEW IMPLEMENTATION: Uses time-window voting within a single continuous scan
        instead of repeated command flooding. This preserves the voting API for
        backward compatibility while fixing the command flooding issue.

        Voting is now based on detection count over time:
        - A tag must be detected at least min_appearances times during the scan

        Args:
            total_cycles: Used to calculate scan_duration if not provided
                         (scan_duration = total_cycles * read_interval)
            min_appearances: Minimum detection count for a tag to be confirmed
            read_interval: Used for scan_duration calculation (default 1.0s)
            idle_break_timeout: Seconds of inactivity before breaking early
            max_cycle_wait: Ignored (for backward compatibility)
            log_each_cycle: Log tags found periodically
            scan_duration: Direct override for scan duration in seconds

        Returns:
            List of tags that passed the voting threshold
        """
        interval = RFID_READ_INTERVAL if read_interval is None else read_interval

        # Calculate scan duration from legacy parameters if not provided
        if scan_duration is None:
            scan_duration = total_cycles * interval

        log_interval = interval if log_each_cycle else scan_duration

        prev_idle = self._idle_break_timeout
        if idle_break_timeout is not None:
            self._idle_break_timeout = idle_break_timeout

        try:
            logger.info(
                "Starting RFID voting scan - duration=%.1fs, need %s+ appearances",
                scan_duration,
                min_appearances,
            )

            result = self.read_rfid_tags_continuous(
                scan_duration=scan_duration,
                toggle_target=True,
                idle_break_timeout=idle_break_timeout,
                log_interval=log_interval,
            )

            detected_tags = result['tags']
            tag_count = result['tag_count']

            # Apply voting threshold based on detection count
            confirmed_tags = [
                tag for tag in detected_tags
                if tag_count.get(tag, 0) >= min_appearances
            ]

            # Adaptive threshold: if we filtered out too many tags (>50%),
            # lower the threshold to capture weak signals
            filtered_ratio = 1.0 - (len(confirmed_tags) / len(detected_tags)) if detected_tags else 0
            if detected_tags and filtered_ratio > 0.5:
                # Lower threshold to 1 to capture all detected tags
                logger.warning(
                    "Voting threshold too aggressive (filtered %.0f%% tags), "
                    "lowering threshold to 1",
                    filtered_ratio * 100,
                )
                confirmed_tags = detected_tags

            # If voting threshold filtered all tags, fall back
            if not confirmed_tags and detected_tags:
                logger.warning(
                    "Voting threshold (%d) filtered all tags, "
                    "falling back to single detection mode",
                    min_appearances,
                )
                confirmed_tags = detected_tags

            # Sort by detection count (most reliable first)
            confirmed_tags = sorted(confirmed_tags, key=lambda t: tag_count.get(t, 0), reverse=True)

            logger.info(
                "RFID voting complete: %d confirmed (from %d detected, threshold=%d)",
                len(confirmed_tags), len(detected_tags), min_appearances,
            )
            logger.info("Tag detection counts: %s", dict(sorted(tag_count.items(), key=lambda x: x[1], reverse=True)))
            logger.info("Confirmed tags: %s", confirmed_tags)

            return confirmed_tags

        except Exception as e:
            logger.error(f"RFID voting read error: {e}")
            return []
        finally:
            self._idle_break_timeout = prev_idle

    def read_rfid_tags_continuous(
        self,
        scan_duration: float = 5.0,
        toggle_target: bool = True,
        idle_break_timeout: Optional[float] = None,
        log_interval: float = 0.5,
        antenna: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Continuous scan with cycle-by-cycle approach (based on master branch).
        This is more reliable than the optimized version that had timing issues.

        Args:
            scan_duration: Total scan time in seconds
            toggle_target: Alternate inventory target each cycle
            idle_break_timeout: Seconds of silence before ending a cycle
            log_interval: Logging interval
            antenna: Override antenna ID (e.g. 0x00, 0x01). None uses default.
        """
        from collections import defaultdict

        tag_count: Dict[str, int] = defaultdict(int)
        bytes_received = 0
        frames_parsed = 0
        self.work_mode_tags.clear()
        self._recv_buffer.clear()

        if not self.connect():
            return {'tags': [], 'tag_count': {}, 'bytes_received': 0, 'frames_parsed': 0}

        # Override antenna if specified (after connect which calls _init_reader)
        if antenna is not None:
            self._set_antenna(antenna)

        try:
            session = 0x01
            repeat = 0x01
            start_time = time.time()
            cycle = 0
            interval = 0.3  # Shorter interval for more cycles in same time

            self.reading = True

            # Set up idle timeout
            prev_idle = self._idle_break_timeout
            if idle_break_timeout is not None:
                self._idle_break_timeout = idle_break_timeout

            logger.info(f"Starting continuous scan for {scan_duration}s...")

            while self.reading:
                now = time.time()
                if now - start_time >= scan_duration:
                    break

                # Toggle target every cycle to capture inverted tags
                target = 0x00 if cycle % 2 == 0 else 0x01
                cmd_payload = bytes([session, target, repeat])

                # Clear tags for this cycle to get fresh detection
                self.work_mode_tags.clear()

                # Send inventory command
                packet = self._build_packet(0x8B, cmd_payload)
                self.socket.sendall(packet)

                # Receive for this cycle
                cycle_start = time.time()
                last_data_time = cycle_start

                while (time.time() - cycle_start) < self._max_cycle_wait:
                    try:
                        self.socket.settimeout(0.1)
                        data = self.socket.recv(4096)
                        if data:
                            last_data_time = time.time()
                            bytes_received += len(data)
                            self._recv_buffer.extend(data)
                            frames_parsed += self._extract_frames_from_buffer()
                        else:
                            if (time.time() - last_data_time) > self._idle_break_timeout:
                                break
                    except socket.timeout:
                        if (time.time() - last_data_time) > self._idle_break_timeout:
                            break
                        continue
                    except Exception as e:
                        logger.error(f"RFID receive error: {e}")
                        break

                # Count tags found in this cycle
                cycle_tags = set(self.work_mode_tags)
                for tag in cycle_tags:
                    tag_count[tag] += 1

                cycle += 1
                time.sleep(interval)

            # Restore idle timeout
            self._idle_break_timeout = prev_idle

            detected_tags = list(tag_count.keys())
            logger.info(f"Scan complete: {len(detected_tags)} tags found, {bytes_received} bytes received")

            return {
                'tags': detected_tags,
                'tag_count': dict(tag_count),
                'bytes_received': bytes_received,
                'frames_parsed': frames_parsed,
            }

        except Exception as e:
            logger.error(f"Scan error: {e}")
            return {'tags': [], 'tag_count': {}, 'bytes_received': bytes_received, 'frames_parsed': frames_parsed}
        finally:
            self.reading = False
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
        Extract frames from receive buffer with robust error recovery.

        Improvement: On checksum failure, use Len field to skip the entire
        failed frame instead of advancing pos by only 1. This prevents cascade
        alignment loss in high-throughput scenarios.

        Returns:
            Number of valid frames extracted
        """
        buf = self._recv_buffer

        # Buffer overflow protection: with fast-switch (0x8A) the reader can
        # send 30+ tags per burst (~30 bytes each = ~1KB).  Allow up to 8KB
        # before giving up on sync recovery.
        MAX_BUFFER_SIZE = 8192
        if len(buf) > MAX_BUFFER_SIZE:
            logger.warning("Buffer overflow (%d bytes) or sync lost, clearing buffer", len(buf))
            buf.clear()
            return 0

        pos = 0
        frames_found = 0
        MAX_FRAME_LEN = 256

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
                logger.debug(f"Invalid frame length {length} at pos {pos}, skipping header")
                pos += 1  # Skip this 0xA0 and look for next
                continue

            # Check if we have the complete frame
            if pos + frame_total_len > len(buf):
                logger.debug(f"Incomplete frame: need {frame_total_len}, have {len(buf) - pos}")
                break

            # Extract and validate frame
            frame = bytes(buf[pos: pos + frame_total_len])
            received_cs = frame[-1]
            # Checksum: hardware appears to include 0xA0 header in calculation
            # Master branch uses frame[:-1], new implementation used frame[1:-1]
            # Using master approach for compatibility
            calc_cs = self._checksum(frame[:-1])  # Include 0xA0, exclude checksum byte

            if received_cs != calc_cs:
                logger.debug(
                    "Checksum mismatch at pos %d: received 0x%02X, calc 0x%02X, frame: %s",
                    pos, received_cs, calc_cs, frame[:min(20, len(frame))].hex(),
                )
                # CRITICAL: On checksum failure, only advance by 1 byte
                # The length field may be corrupted, so skipping the whole frame
                # could cause us to miss valid frames that follow
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
            self._recv_buffer = bytearray(buf[pos:])

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
            # 0x8A = fast switch antenna inventory response (contains tag data)
            self._parse_tag_data_bytes(data)
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

        while pos < len(data):
            if pos + 6 > len(data):
                break

            freq_ant = data[pos]
            pos += 1

            pc_byte1 = data[pos]
            pc_byte2 = data[pos + 1]
            pos += 2
            pc_value = (pc_byte1 << 8) | pc_byte2

            epc_word_len = (pc_value >> 11) & 0x1F
            epc_byte_len = epc_word_len * 2

            if pos + epc_byte_len > len(data):
                break

            epc_data = data[pos: pos + epc_byte_len]
            pos += epc_byte_len

            if pos >= len(data):
                break

            rssi_byte = data[pos]
            pos += 1

            epc_hex = epc_data.hex().upper()
            rssi_dbm = rssi_byte - 129 if rssi_byte < 129 else rssi_byte - 129
            if self._validate_epc(epc_hex) and epc_hex not in IGNORED_TAGS:
                self.work_mode_tags.add(epc_hex)
                logger.debug(f"Tag: EPC={epc_hex}, RSSI={rssi_dbm}dBm")
                if self._tag_callback:
                    self._tag_callback(epc_hex)

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
        self._hid_reader = None
        self._rfid_reader = None
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
        """
        Initialize NFC reader with multiple fallback modes.

        Priority:
        1. Serial mode (optimal for EMI stability, requires serial firmware)
        2. HIDRAW mode (direct hidraw access, avoids Linux input event noise)
        3. HID keyboard mode (fallback using evdev)
        """
        if self._nfc_mode == "none":
            logger.info("NFC reader disabled")
            return

        self._nfc_reader = None
        self._hid_reader = None

        # Try 1: Serial mode (optimal, requires serial firmware)
        if self._nfc_mode in ("auto", "serial"):
            try:
                self._nfc_reader = NFCQRReader()
                if self._nfc_reader.is_connected():
                    logger.info("Serial NFC reader initialized")
                    return
                else:
                    self._nfc_reader.close()
                    self._nfc_reader = None
            except Exception as e:
                logger.debug(f"Serial NFC reader not available: {e}")

        # Try 2: HIDRAW mode (direct access, less noise than evdev)
        if self._nfc_mode in ("auto", "hidraw"):
            try:
                self._hid_reader = HIDRawReader()
                if self._hid_reader.is_available():
                    logger.info("HIDRAW NFC reader initialized (direct mode)")
                    return
                else:
                    self._hid_reader.close()
                    self._hid_reader = None
            except Exception as e:
                logger.debug(f"HIDRAW NFC reader not available: {e}")

        # Try 3: HID keyboard mode (fallback using evdev)
        if self._nfc_mode in ("auto", "hid"):
            try:
                from .hid_keyboard_reader import HIDKeyboardReader, EVDEV_AVAILABLE
                if EVDEV_AVAILABLE:
                    self._hid_reader = HIDKeyboardReader()
                    if self._hid_reader.is_available():
                        logger.info("HID Keyboard NFC reader initialized (evdev mode)")
                        return
                    else:
                        self._hid_reader = None
            except Exception as e:
                logger.debug(f"HID Keyboard reader not available: {e}")

        logger.warning("No NFC reader available")

    def read_nfc(self, timeout: float = 30.0) -> Optional[str]:
        """Read NFC card UID (supports serial and HID modes)."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Try serial reader first
            if self._nfc_reader and self._nfc_reader.is_connected():
                result = self._nfc_reader.read_card()
                if result:
                    if result['type'] == 'nfc':
                        return result['data']
                    else:
                        self._last_read_data = result['data']
                        self._last_read_type = 'qr'

            # Try HID reader (hidraw or evdev mode)
            if self._hid_reader and self._hid_reader.is_available():
                result = self._hid_reader.read_card(timeout=0.1)
                if result:
                    if result['type'] == 'nfc':
                        return result['data']
                    else:
                        self._last_read_data = result['data']
                        self._last_read_type = 'qr'

            time.sleep(0.05)

        return None

    def read_qr(self, timeout: float = 30.0) -> Optional[str]:
        """Read QR code (supports serial and HID modes)."""
        start_time = time.time()

        # Check if we have cached QR data from previous read
        if hasattr(self, '_last_read_data') and getattr(self, '_last_read_type', None) == 'qr':
            data = self._last_read_data
            self._last_read_data = None
            self._last_read_type = None
            logger.info(f"QR code returned from cache: {data[:30]}...")
            return data

        while time.time() - start_time < timeout:
            # Try serial reader first
            if self._nfc_reader and self._nfc_reader.is_connected():
                result = self._nfc_reader.read_card()
                if result:
                    if result['type'] == 'qr':
                        return result['data']
                    else:
                        self._last_read_data = result['data']
                        self._last_read_type = 'nfc'

            # Try HID reader (hidraw or evdev mode)
            if self._hid_reader and self._hid_reader.is_available():
                result = self._hid_reader.read_card(timeout=0.1)
                if result:
                    if result['type'] == 'qr':
                        return result['data']
                    else:
                        self._last_read_data = result['data']
                        self._last_read_type = 'nfc'

            time.sleep(0.05)

        return None

    def read_card_auto(self, timeout: float = 30.0) -> Optional[Dict[str, str]]:
        """
        Read card and automatically detect type (NFC or QR).

        Supports both serial and HID modes.
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Try serial reader first (if available)
            if self._nfc_reader and self._nfc_reader.is_connected():
                result = self._nfc_reader.read_card()
                if result:
                    return result

            # Try HID reader (hidraw or evdev mode)
            if self._hid_reader and self._hid_reader.is_available():
                result = self._hid_reader.read_card(timeout=0.1)
                if result:
                    return result

            time.sleep(0.05)

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
        scan_duration: Optional[float] = None,
    ) -> List[str]:
        """
        Read RFID tags with voting mechanism for better accuracy.

        Args:
            total_cycles: Used to calculate scan_duration if not provided
            min_appearances: Minimum detection count for a tag to be confirmed
            read_interval: Used for scan_duration calculation
            idle_break_timeout: Seconds of inactivity before breaking early
            max_cycle_wait: Ignored (for backward compatibility)
            log_each_cycle: Log tags found periodically
            scan_duration: Direct override for scan duration in seconds

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
            scan_duration=scan_duration,
        )

    def read_rfid_tags_inventory(
        self,
        scan_passes: int = 3,
        pass_duration: float = 5.0,
        antennas: Optional[List[int]] = None,
    ) -> List[str]:
        """
        Inventory-optimized RFID scan for stable counting.

        Performs multiple scan passes across configured antennas and returns
        union of all detected tags.

        Args:
            scan_passes: Number of scan passes (default 3)
            pass_duration: Duration of each pass in seconds (default 5.0)
            antennas: List of antenna IDs to cycle through

        Returns:
            List of unique tags detected across all passes
        """
        if not self._rfid_reader:
            return []

        return self._rfid_reader.read_rfid_tags_inventory(
            scan_passes=scan_passes,
            pass_duration=pass_duration,
            antennas=antennas,
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

        if self._hid_reader:
            self._hid_reader.close()

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
        # Check NFC status (serial or HID mode)
        nfc_status = "error"
        nfc_mode = "none"
        if self._nfc_reader and self._nfc_reader.is_connected():
            nfc_status = "ok"
            nfc_mode = "serial"
        elif self._hid_reader and self._hid_reader.is_available():
            nfc_status = "ok"
            # Detect mode based on class name
            nfc_mode = getattr(self._hid_reader, '__class__', None).__name__ if self._hid_reader else "hid"

        return {
            "status": "healthy" if self._initialized else "not_initialized",
            "mode": "raspberry_pi",
            "rpi_available": RPI_AVAILABLE,
            "solenoids": "ok" if self._initialized else "error",
            "nfc": nfc_status,
            "nfc_mode": nfc_mode,
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
