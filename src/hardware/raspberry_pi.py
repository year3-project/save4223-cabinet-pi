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
    try:
        import smbus2 as smbus
    except ImportError:
        import smbus
    import serial
    RPI_AVAILABLE = True
except ImportError as e:
    RPI_AVAILABLE = False
    logging.warning(f"RPi libraries not available ({e}) - running in simulation mode")

from .base import HardwareInterface, DrawerState, LEDColor

logger = logging.getLogger(__name__)


# Configuration constants (from legacy config.py)
SERVO_PINS = [8, 9, 10, 11]
SERVO_OPEN_POSITION = 80
SERVO_CLOSE_POSITION = [30, 20, 20, 20]

DRAWER_SWITCH_PINS = [12, 16, 20, 21]
CLOSE_BUTTON_PIN = 26

# LED pins (GRY order: Green, Red, Yellow)
LED_1 = [24, 23, 25]
LED_2 = [6, 5, 13]
LED_3 = [15, 14, 18]
LED_4 = [17, 27, 22]
LEDs = [LED_1, LED_2, LED_3, LED_4]

# RFID configuration
RFID_HOST = '192.168.0.178'
RFID_PORT = 4001
RFID_READ_CYCLES = 5
RFID_READ_INTERVAL = 0.5
RFID_ADDRESS = 0xFF
IGNORED_TAGS = {"00B07A15306008EFF68E8F54"}

# NFC/QR configuration
NFC_BAUD_RATE = 115200


class PCA9685:
    """PCA9685 PWM controller for servos."""

    __SUBADR1 = 0x02
    __SUBADR2 = 0x03
    __SUBADR3 = 0x04
    __MODE1 = 0x00
    __PRESCALE = 0xFE
    __LED0_ON_L = 0x06
    __LED0_ON_H = 0x07
    __LED0_OFF_L = 0x08
    __LED0_OFF_H = 0x09

    def __init__(self, address=0x40, bus_num=1):
        if RPI_AVAILABLE:
            self.bus = smbus.SMBus(bus_num)
        else:
            self.bus = None
        self.address = address
        self.freq = 50

        if self.bus:
            self.write(self.__MODE1, 0x00)
            self.setPWMFreq(50)

    def write(self, reg, value):
        if self.bus:
            self.bus.write_byte_data(self.address, reg, value)

    def read(self, reg):
        if self.bus:
            return self.bus.read_byte_data(self.address, reg)
        return 0

    def setPWMFreq(self, freq):
        prescaleval = 25000000.0 / 4096.0 / float(freq) - 1.0
        prescale = int(prescaleval + 0.5)

        oldmode = self.read(self.__MODE1)
        newmode = (oldmode & 0x7F) | 0x10
        self.write(self.__MODE1, newmode)
        self.write(self.__PRESCALE, prescale)
        self.write(self.__MODE1, oldmode)
        time.sleep(0.005)
        self.write(self.__MODE1, oldmode | 0x80)
        self.freq = freq

    def setPWM(self, channel, on, off):
        self.write(self.__LED0_ON_L + 4*channel, on & 0xFF)
        self.write(self.__LED0_ON_H + 4*channel, (on >> 8) & 0xFF)
        self.write(self.__LED0_OFF_L + 4*channel, off & 0xFF)
        self.write(self.__LED0_OFF_H + 4*channel, (off >> 8) & 0xFF)

    def setServoPulse(self, channel, pulse_us):
        period_us = 1_000_000.0 / float(self.freq)
        ticks = int(round((pulse_us / period_us) * 4096.0))
        ticks = max(0, min(4095, ticks))
        self.setPWM(channel, 0, ticks)

    def set_servo_angle(self, channel, angle):
        """Set servo angle (0-180 degrees)."""
        pulse_us = 1000 * (angle * 2.27 / 180.0) + 500
        self.setServoPulse(channel, pulse_us)


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

    def __init__(self, num_drawers: int = 4, num_leds: int = 8):
        self.num_drawers = num_drawers
        self.num_leds = num_leds
        self._initialized = False
        self._drawer_states = {i: DrawerState.CLOSED for i in range(num_drawers)}
        self._servo_manager = None
        self._nfc_reader = None
        self._rfid_reader = None

    def initialize(self) -> None:
        """Initialize hardware components."""
        if not RPI_AVAILABLE:
            logger.warning("RPi libraries not available - running in simulation mode")
            self._initialized = True
            return

        # Initialize GPIO
        GPIO.setmode(GPIO.BCM)

        # Setup servo pins
        for pin in SERVO_PINS:
            GPIO.setup(pin, GPIO.OUT)

        # Setup drawer switch pins
        for pin in DRAWER_SWITCH_PINS:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        # Setup LED pins
        for led_group in LEDs:
            for pin in led_group:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.HIGH)

        # Setup close button
        GPIO.setup(CLOSE_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_OFF)

        # Initialize servo manager
        try:
            self._servo_manager = PCA9685()
            self._servo_manager.setPWMFreq(50)
            logger.info("Servo controller initialized")
        except Exception as e:
            logger.error(f"Failed to initialize servo controller: {e}")

        # Initialize NFC/QR reader
        try:
            self._nfc_reader = NFCQRReader()
        except Exception as e:
            logger.error(f"Failed to initialize NFC reader: {e}")

        # Initialize RFID reader
        try:
            self._rfid_reader = RFIDReader()
        except Exception as e:
            logger.error(f"Failed to initialize RFID reader: {e}")

        self._initialized = True
        logger.info("Raspberry Pi hardware initialized")

    def read_nfc(self, timeout: float = 30.0) -> Optional[str]:
        """Read NFC card UID."""
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

    def unlock_drawer(self, drawer_id: int) -> bool:
        """Unlock a specific drawer."""
        if not self._servo_manager or drawer_id < 0 or drawer_id >= len(SERVO_PINS):
            return False

        try:
            pin = SERVO_PINS[drawer_id]
            angle = SERVO_OPEN_POSITION
            self._servo_manager.set_servo_angle(pin, angle)
            self._drawer_states[drawer_id] = DrawerState.OPEN
            logger.info(f"Drawer {drawer_id} unlocked")
            return True
        except Exception as e:
            logger.error(f"Failed to unlock drawer {drawer_id}: {e}")
            return False

    def lock_drawer(self, drawer_id: int) -> bool:
        """Lock a specific drawer."""
        if not self._servo_manager or drawer_id < 0 or drawer_id >= len(SERVO_PINS):
            return False

        try:
            pin = SERVO_PINS[drawer_id]
            angle = SERVO_CLOSE_POSITION[drawer_id] if drawer_id < len(SERVO_CLOSE_POSITION) else 20
            self._servo_manager.set_servo_angle(pin, angle)
            self._drawer_states[drawer_id] = DrawerState.CLOSED
            logger.info(f"Drawer {drawer_id} locked")
            return True
        except Exception as e:
            logger.error(f"Failed to lock drawer {drawer_id}: {e}")
            return False

    def unlock_all(self) -> bool:
        """Unlock all drawers."""
        if not self._servo_manager:
            return False

        try:
            for i in range(min(self.num_drawers, len(SERVO_PINS))):
                self.unlock_drawer(i)
            time.sleep(0.5)
            return True
        except Exception as e:
            logger.error(f"Failed to unlock all drawers: {e}")
            return False

    def lock_all(self) -> bool:
        """Lock all drawers."""
        if not self._servo_manager:
            return False

        try:
            for i in range(min(self.num_drawers, len(SERVO_PINS))):
                self.lock_drawer(i)
            time.sleep(0.5)
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
            # HIGH means open (switch not pressed)
            if GPIO.input(pin) == GPIO.HIGH:
                return DrawerState.OPEN
            else:
                return DrawerState.CLOSED
        except Exception as e:
            logger.error(f"Failed to read drawer {drawer_id} state: {e}")
            return DrawerState.UNKNOWN

    def get_all_drawer_states(self) -> Dict[int, DrawerState]:
        """Get all drawer states."""
        states = {}
        for i in range(self.num_drawers):
            states[i] = self.get_drawer_state(i)
        return states

    def are_all_drawers_closed(self) -> bool:
        """Check if all drawers are closed."""
        if not RPI_AVAILABLE:
            return all(s == DrawerState.CLOSED for s in self._drawer_states.values())

        try:
            for pin in DRAWER_SWITCH_PINS[:self.num_drawers]:
                if GPIO.input(pin) == GPIO.HIGH:  # HIGH means open
                    return False
            return True
        except Exception as e:
            logger.error(f"Failed to check drawer states: {e}")
            return False

    def set_led(self, index: int, color: LEDColor, brightness: float = 1.0) -> None:
        """Set LED color."""
        if not RPI_AVAILABLE or index < 0 or index >= len(LEDs):
            return

        try:
            led_group = LEDs[index]

            # Turn off all colors first
            for pin in led_group:
                GPIO.output(pin, GPIO.HIGH)

            # Turn on specified color (LOW = on for active-low LEDs)
            if color == LEDColor.GREEN:
                GPIO.output(led_group[0], GPIO.LOW)
            elif color == LEDColor.RED:
                GPIO.output(led_group[1], GPIO.LOW)
            elif color == LEDColor.YELLOW:
                GPIO.output(led_group[2], GPIO.LOW)

        except Exception as e:
            logger.error(f"Failed to set LED {index}: {e}")

    def set_all_leds(self, color: LEDColor, brightness: float = 1.0) -> None:
        """Set all LEDs to same color."""
        for i in range(min(self.num_drawers, len(LEDs))):
            self.set_led(i, color, brightness)

    def led_pattern(self, pattern: str, color: LEDColor, duration: float = 1.0) -> None:
        """Run LED pattern."""
        if pattern == "blink":
            for _ in range(int(duration * 2)):
                self.set_all_leds(color)
                time.sleep(0.25)
                self.set_all_leds(LEDColor.OFF)
                time.sleep(0.25)
        elif pattern == "pulse":
            self.set_all_leds(color)
            time.sleep(duration)
        elif pattern == "solid":
            self.set_all_leds(color)

    def beep(self, duration: float = 0.1, frequency: Optional[int] = None) -> None:
        """Play beep sound."""
        # TODO: Implement buzzer if available
        logger.debug(f"Beep: {duration}s @ {frequency}Hz")

    def beep_success(self) -> None:
        """Success beep pattern."""
        self.beep(0.1, 2000)

    def beep_error(self) -> None:
        """Error beep pattern."""
        self.beep(0.2, 500)
        time.sleep(0.1)
        self.beep(0.2, 500)

    def beep_warning(self) -> None:
        """Warning beep pattern."""
        self.beep(0.3, 1000)

    def cleanup(self) -> None:
        """Cleanup resources."""
        if self._nfc_reader:
            self._nfc_reader.close()

        if self._rfid_reader:
            self._rfid_reader.disconnect()

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
            "servo": "ok" if self._servo_manager else "error",
            "nfc": "ok" if self._nfc_reader and self._nfc_reader._test_connection() else "error",
            "rfid": "ok" if self._rfid_reader else "error",
            "drawers": self.num_drawers,
            "leds": self.num_leds,
        }
