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
RFID_READ_CYCLES = 5
RFID_READ_INTERVAL = 0.5
RFID_ADDRESS = 0xFF
IGNORED_TAGS = {"00B07A15306008EFF68E8F54"}

# NFC/QR configuration
NFC_BAUD_RATE = 115200


class NFCQRReader:
    """USB NFC/QR code reader."""

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
        """Read NFC card UID."""
        if not self.ser or not self.ser.is_open:
            return None

        try:
            # Command to read UID
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
                                logger.info(f"NFC card detected: {uid_decimal}")
                                return uid_decimal
            return None

        except Exception as e:
            logger.error(f"NFC read error: {e}")
            return None

    def read_qr_code(self) -> Optional[str]:
        """Read QR code."""
        try:
            if self.ser and self.ser.in_waiting > 0:
                self.ser.reset_input_buffer()
                qr_data = self.ser.readline().decode('utf-8', errors='ignore').strip()
                if qr_data and len(qr_data) > 0:
                    logger.info(f"QR code detected: {qr_data}")
                    return qr_data
            return None
        except Exception as e:
            logger.error(f"QR read error: {e}")
            return None

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

    def read_rfid_tags_voting(self, total_cycles: int = 5, min_appearances: int = 2) -> List[str]:
        """
        Read RFID tags with voting mechanism for better accuracy.

        A tag is considered present only if it appears in at least min_appearances
        out of total_cycles scans. This reduces false positives from sporadic reads.

        Args:
            total_cycles: Total number of scan cycles (default 5)
            min_appearances: Minimum times a tag must appear to be considered present (default 2)

        Returns:
            List of tags that passed the voting threshold
        """
        from collections import Counter

        if not self.connect():
            return []

        tag_counter = Counter()
        cycle = 0
        self.reading = True

        logger.info(f"Starting RFID voting scan - {total_cycles} cycles, need {min_appearances} appearances")

        try:
            session = 0x01
            target = 0x00
            repeat = 0x01
            cmd_payload = bytes([session, target, repeat])

            while self.reading and cycle < total_cycles:
                # Clear tags for this cycle to get fresh detection
                cycle_tags = set()
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

                logger.debug(f"[Cycle {cycle+1}/{total_cycles}] Found: {list(cycle_tags)}")
                cycle += 1
                time.sleep(RFID_READ_INTERVAL)

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
            self.stop_reading()
            self.disconnect()

    def _receive_and_process(self):
        """Receive and process RFID data."""
        start_time = time.time()
        last_data_time = time.time()

        while self.reading and (time.time() - start_time) < self._max_cycle_wait:
            try:
                self.socket.settimeout(0.1)
                data = self.socket.recv(4096)
                if data:
                    last_data_time = time.time()
                    self._recv_buffer.extend(data)
                    self._extract_frames_from_buffer()
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

    def _extract_frames_from_buffer(self):
        """Extract frames from receive buffer."""
        buf = self._recv_buffer
        pos = 0

        while pos + 5 <= len(buf):
            if buf[pos] != 0xA0:
                pos += 1
                continue

            length = buf[pos + 1]
            frame_total_len = 2 + length

            if pos + frame_total_len > len(buf):
                break

            frame = bytes(buf[pos: pos + frame_total_len])
            received_cs = frame[-1]
            calc_cs = self._checksum(frame[:-1])

            if received_cs != calc_cs:
                pos += 1
                continue

            try:
                self._parse_frame(frame)
            except Exception as e:
                logger.debug(f"Frame parse error: {e}")

            pos += frame_total_len

        if pos > 0:
            remaining = buf[pos:]
            self._recv_buffer = bytearray(remaining)

    def _parse_frame(self, frame: bytes):
        """Parse a single frame."""
        length = frame[1]
        cmd = frame[3]
        data_len = max(0, length - 3)
        data = frame[4:4 + data_len] if data_len > 0 else b''

        if cmd == 0x8B:
            self._parse_tag_data_bytes(data)

    def _parse_tag_data_bytes(self, data: bytes):
        """Parse tag data from frame."""
        pos = 0
        while pos < len(data):
            if pos + 4 > len(data):
                break

            freq_ant = data[pos]
            pos += 1
            antenna = (freq_ant & 0x03) + 1

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
            if self._validate_epc(epc_hex) and epc_hex not in IGNORED_TAGS:
                self.work_mode_tags.add(epc_hex)

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
        if self._hid_reader and self._hid_reader.is_available():
            return self._hid_reader.read_card(timeout=timeout)

        if not self._nfc_reader:
            return None

        start_time = time.time()
        while time.time() - start_time < timeout:
            uid = self._nfc_reader.read_nfc_card()
            if uid:
                return uid
            time.sleep(0.1)

        return None

    def read_qr(self, timeout: float = 30.0) -> Optional[str]:
        """Read QR code."""
        if self._hid_reader and self._hid_reader.is_available():
            result = self._hid_reader.read_card(timeout=timeout)
            if result:
                return result

        if not self._nfc_reader:
            return None

        start_time = time.time()
        while time.time() - start_time < timeout:
            qr = self._nfc_reader.read_qr_code()
            if qr:
                return qr
            time.sleep(0.1)

        return None

    def read_rfid_tags(self, drawer_id: Optional[int] = None) -> List[str]:
        """Read RFID tags."""
        if not self._rfid_reader:
            return []

        return self._rfid_reader.read_rfid_tags_multiple()

    def read_rfid_tags_voting(self, total_cycles: int = 5, min_appearances: int = 2) -> List[str]:
        """
        Read RFID tags with voting mechanism for better accuracy.

        A tag is considered present only if it appears in at least min_appearances
        out of total_cycles scans. This reduces false positives from sporadic reads.

        Args:
            total_cycles: Total number of scan cycles (default 5)
            min_appearances: Minimum times a tag must appear to be considered present (default 2)

        Returns:
            List of tags that passed the voting threshold
        """
        if not self._rfid_reader:
            return []

        return self._rfid_reader.read_rfid_tags_voting(total_cycles, min_appearances)

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
