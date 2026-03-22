#!/usr/bin/env python3
"""
Smart Cabinet Pi - Main Entry Point
Raspberry Pi controller for Save4223 smart tool cabinet system.
"""

import time
import signal
import sys
import os
import logging
import uuid
import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from state_machine import StateMachine, SystemState
from api_client import APIClient, APIError
from local_db import LocalDB
from sync_worker import SyncWorker
from pairing_handler import PairingHandler, PairingResult
from inventory_manager import InventoryManager
from config import CONFIG

# Configure logging
log_path = Path('/var/log/cabinet.log') if Path('/var/log').exists() and os.access('/var/log', os.W_OK) else Path(__file__).parent.parent / 'data' / 'cabinet.log'
log_path.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_path)
    ]
)
logger = logging.getLogger(__name__)

# Hardware import
from hardware import RaspberryPiHardware as HardwareController
logger.info("Using RaspberryPiHardware")

# Display import (optional - falls back to console if nicegui not available)
try:
    sys.path.insert(0, str(Path(__file__).parent.parent / 'display'))
    from display import DisplayThread
    DISPLAY_AVAILABLE = True
except ImportError as e:
    DISPLAY_AVAILABLE = False
    logger.warning(f"Display not available: {e}")


class SmartCabinet:
    """Main cabinet controller class with full offline support."""

    # Operation modes
    MODE_NORMAL = 'normal'
    MODE_PAIRING = 'pairing'

    def __init__(self):
        self.running = False
        self.mode = self.MODE_NORMAL

        # Session state
        self.current_user_id: Optional[str] = None
        self.current_user_name: Optional[str] = 'Unknown'
        self.current_card_uid: Optional[str] = None
        self.session_id: Optional[str] = None
        self.session_start_time: Optional[datetime] = None
        self._pairing_token: Optional[str] = None  # For QR-first pairing flow

        # Initialize components
        logger.info("Initializing Smart Cabinet...")

        self.state_machine = StateMachine()
        self.hardware = HardwareController()

        # SSL configuration
        ssl_config = CONFIG.get('ssl', {})
        cert_path = ssl_config.get('cert_path') if ssl_config.get('verify') else None

        self.api = APIClient(
            base_url=CONFIG['server_url'],
            edge_secret=CONFIG['edge_secret'],
            timeout=CONFIG.get('api', {}).get('timeout', 5),
            cert_path=cert_path,
            max_retries=CONFIG.get('api', {}).get('max_retries', 3),
            retry_delay=CONFIG.get('api', {}).get('retry_delay', 1.0)
        )

        self.local_db = LocalDB(CONFIG['db_path'])
        self.sync_worker = SyncWorker(
            self.local_db, self.api,
            interval=CONFIG.get('sync_interval', 60)
        )
        self.pairing_handler = PairingHandler(self.api, self.local_db)
        self.inventory = InventoryManager(self.local_db)

        # Initialize display (optional) - pass hardware for real-time drawer status
        self.display = None
        if DISPLAY_AVAILABLE and CONFIG.get('display', {}).get('enabled', True):
            try:
                display_config = CONFIG.get('display', {})
                self.display = DisplayThread(
                    width=display_config.get('width', 800),
                    height=display_config.get('height', 480),
                    fullscreen=display_config.get('fullscreen', True),
                    hardware=self.hardware  # Pass hardware for real-time status
                )
                self.display.start()
                logger.info("Display started")
                # Give display time to initialize
                import time
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"Failed to start display: {e}")

        # Setup handlers
        self._setup_signal_handlers()
        self._setup_state_handlers()

        # Start sync worker
        self.sync_worker.start()

        # Initial sync
        self._initial_sync()

        logger.info("Smart Cabinet initialized successfully")

    def _initial_sync(self):
        """Perform initial sync on startup."""
        logger.info("Performing initial sync...")
        try:
            if self.api.health_check():
                self.sync_worker.sync_inventory_cache()
                logger.info("Initial sync completed")
            else:
                logger.warning("Server unavailable, operating in offline mode")
        except Exception as e:
            logger.warning(f"Initial sync failed: {e}, operating in offline mode")

    def _setup_signal_handlers(self):
        """Setup graceful shutdown handlers."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def _setup_state_handlers(self):
        """Register state machine handlers."""
        self.state_machine.on_enter(SystemState.LOCKED, self._on_locked)
        self.state_machine.on_enter(SystemState.AUTHENTICATING, self._on_authenticating)
        self.state_machine.on_enter(SystemState.UNLOCKED, self._on_unlocked)
        self.state_machine.on_enter(SystemState.SCANNING, self._on_scanning)

    def _send_to_display(self, message: dict):
        """Send update to local dashboard."""
        logger.info(f"[DISPLAY] {message['type']}: {json.dumps(message, default=str)}")

        # Send to pygame display if available
        if self.display:
            try:
                self.display.send_message(message)
            except Exception as e:
                logger.debug(f"Display update failed: {e}")

    # =================================================================================
    # State Handlers
    # =================================================================================

    def _on_locked(self, context=None):
        """Handle LOCKED state entry."""
        logger.info("=" * 50)
        logger.info("State: LOCKED - Ready for card/QR scan")
        logger.info("=" * 50)

        self.hardware.set_all_leds('off')
        self.hardware.lock_all()

        # Reset session state
        self.current_user_id = None
        self.current_user_name = 'Unknown'
        self.current_card_uid = None
        self.session_id = None
        self.session_start_time = None

        self._send_to_display({
            'type': 'STATE_CHANGE',
            'state': 'LOCKED',
            'message': 'Tap card or scan QR code to open'
        })

    def _on_authenticating(self, context=None):
        """Handle AUTHENTICATING state entry."""
        logger.info("State: AUTHENTICATING")
        self.hardware.set_all_leds('yellow')

        self._send_to_display({
            'type': 'STATE_CHANGE',
            'state': 'AUTHENTICATING',
            'message': 'Reading card...'
        })

        # Use card already captured in _handle_locked, or wait for a new scan
        card_uid = self.current_card_uid or self.hardware.read_nfc(timeout=30)

        if not card_uid:
            logger.warning("Authentication timeout - no card detected")
            self.hardware.beep_error()
            self._send_to_display({
                'type': 'AUTH_FAILURE',
                'error': 'Timeout - no card detected'
            })
            time.sleep(2)
            self.state_machine.transition(SystemState.LOCKED)
            return

        self.current_card_uid = card_uid
        logger.info(f"Card detected: {card_uid[:10]}...")

        # Check if in pairing mode
        if self.mode == self.MODE_PAIRING:
            self._handle_pairing_scan(card_uid)
            return

        # Normal authentication flow with 5-second total timeout
        import threading
        auth_result = [None]
        def do_auth():
            auth_result[0] = self._authenticate(card_uid)
        auth_thread = threading.Thread(target=do_auth)
        auth_thread.start()
        auth_thread.join(timeout=5)  # 5 second max for auth
        if auth_thread.is_alive():
            logger.warning("Authentication timed out after 5 seconds")
            self.hardware.beep_error()
            self._send_to_display({
                'type': 'AUTH_FAILURE',
                'error': 'Authentication timeout'
            })
            time.sleep(2)
            self.state_machine.transition(SystemState.LOCKED)
            return
        result = auth_result[0]

        if result.get('authorized'):
            self._handle_auth_success(result)
        else:
            self._handle_auth_failure(result)

    def _handle_auth_success(self, result: Dict[str, Any]):
        """Handle successful authentication."""
        self.current_user_id = result['user_id']
        self.current_user_name = result.get('user_name', 'Unknown')
        self.session_id = str(uuid.uuid4())
        self.session_start_time = datetime.now()

        logger.info(f"Authenticated: {self.current_user_name} ({self.current_user_id})")

        # Log access
        self.local_db.log_access(
            card_uid=self.current_card_uid,
            user_id=self.current_user_id,
            user_name=self.current_user_name,
            session_id=self.session_id,
            action='AUTH_SUCCESS'
        )

        self._send_to_display({
            'type': 'AUTH_SUCCESS',
            'user': {
                'id': self.current_user_id,
                'name': self.current_user_name,
                'email': result.get('email', '')
            },
            'session_id': self.session_id
        })

        # Start inventory session
        self.inventory.start_session(self.session_id, self.current_user_id)

        self.state_machine.transition(SystemState.UNLOCKED)

    def _handle_auth_failure(self, result: Dict[str, Any]):
        """Handle authentication failure."""
        reason = result.get('reason', 'Access denied')
        logger.warning(f"Authentication failed: {reason}")

        # Log access
        self.local_db.log_access(
            card_uid=self.current_card_uid,
            user_id=None,
            action='AUTH_FAILURE'
        )

        # Check if card is unpaired (needs pairing)
        if 'not registered' in reason.lower() or 'card not found' in reason.lower():
            logger.info("Unpaired card detected, offering pairing mode")
            self._send_to_display({
                'type': 'PAIRING_MODE',
                'message': 'Card not registered. Please use web app to generate pairing code.'
            })

        self.hardware.set_all_leds('red')
        self.hardware.beep_error()

        self._send_to_display({
            'type': 'AUTH_FAILURE',
            'error': reason
        })

        time.sleep(3)
        self.state_machine.transition(SystemState.LOCKED)

    def _authenticate(self, card_uid: str) -> Dict[str, Any]:
        """
        Authenticate card with local cache first, then remote API.

        Returns:
            Authentication result dict
        """
        # Check local cache first (fast path)
        cached = self.local_db.get_cached_auth(card_uid)
        if cached:
            logger.info("Using cached authentication (local)")
            cached['source'] = 'cache'
            return cached

        # Not in cache - try API if online
        if self.sync_worker.is_online():
            try:
                result = self.api.authorize(card_uid, CONFIG['cabinet_id'])
                # Cache successful auth
                self.local_db.cache_auth(
                    card_uid, result,
                    ttl=3600 * 24 * 7  # 7 days
                )
                result['source'] = 'server'
                return result
            except APIError as e:
                logger.warning(f"API auth failed: {e}")

        return {'authorized': False, 'reason': 'Card not registered'}

    def _on_unlocked(self, context=None):
        """Handle UNLOCKED state entry."""
        logger.info("State: UNLOCKED")
        self.hardware.set_all_leds('green')
        self.hardware.unlock_all()
        self.hardware.beep_success()

        # Capture start snapshot (RFID tags present when unlocked)
        logger.info("Capturing start RFID snapshot...")
        # Use voting method for better accuracy (10 cycles, need 3+ appearances)
        start_tags = self.hardware.read_rfid_tags_voting()
        logger.info(f"Start tags: {start_tags}")
        self.inventory.capture_start_snapshot(start_tags)

        self.local_db.log_access(
            card_uid=self.current_card_uid,
            user_id=self.current_user_id,
            user_name=self.current_user_name,
            session_id=self.session_id,
            action='DOOR_OPEN',
            tags_found=start_tags
        )

        self._send_to_display({
            'type': 'STATE_CHANGE',
            'state': 'UNLOCKED',
            'user': {'name': self.current_user_name} if self.current_user_name else None,
            'message': f'Welcome {self.current_user_name}! Take or return tools, then tap card again to close.',
            'session_id': self.session_id,
            'start_tags': len(start_tags)
        })

        # Wait for user to finish
        unlock_time = time.time()
        session_timeout = CONFIG.get('session_timeout', 300)  # 5 minutes default

        while self.running and (time.time() - unlock_time) < session_timeout:
            # Check if same card scanned (close command)
            card = self.hardware.read_nfc(timeout=0.5)

            if card == self.current_card_uid:
                if self.hardware.are_all_drawers_closed():
                    logger.info("Close command received, all drawers closed")
                    self._send_to_display({
                        'type': 'STATE_CHANGE',
                        'state': 'RFID_SCANNING',
                        'message': 'Closing session, scanning inventory...'
                    })
                    self.state_machine.transition(SystemState.SCANNING)
                    return
                else:
                    logger.info("Please close all drawers first")
                    self.hardware.beep_warning()
                    # Red blink warning (matches test_hardware.py)
                    self.hardware.led_pattern('blink', 'red', duration=0.6)
                    self._send_to_display({
                        'type': 'WARNING',
                        'message': 'Please close all drawers first'
                    })

            # Update LED per drawer status
            for i in range(CONFIG.get('num_drawers', 4)):
                drawer_state = self.hardware.get_drawer_state(i)
                if drawer_state.value == 'open':
                    self.hardware.set_led(i, 'red')
                else:
                    self.hardware.set_led(i, 'green')

            time.sleep(0.1)

        # Session timeout
        logger.warning("Session timeout")
        self.hardware.beep_error()
        self._send_to_display({
            'type': 'TIMEOUT',
            'message': 'Session timeout'
        })
        self.state_machine.transition(SystemState.SCANNING)

    def _on_scanning(self, context=None):
        """Handle SCANNING state entry (end of session)."""
        logger.info("State: SCANNING - Finalizing session")
        self.hardware.lock_all()
        # Blue chase during RFID scan (matches test_hardware.py)
        self.hardware.led_pattern('chase', 'blue', duration=2.0)

        # Capture end snapshot
        logger.info("Capturing end RFID snapshot...")
        end_tags = self._scan_rfid()
        logger.info(f"End tags: {end_tags}")

        self.local_db.log_access(
            card_uid=self.current_card_uid,
            user_id=self.current_user_id,
            user_name=self.current_user_name,
            session_id=self.session_id,
            action='DOOR_CLOSE',
            tags_found=end_tags
        )

        # Calculate diff
        borrowed, returned = self.inventory.capture_end_snapshot(end_tags)

        logger.info(f"Session summary: {len(borrowed)} borrowed, {len(returned)} returned")

        # Save session diff
        start_rfids = list(self.inventory._session_start_rfids or [])
        self.local_db.save_session_diff(
            session_id=self.session_id,
            user_id=self.current_user_id,
            user_name=self.current_user_name,
            borrowed=borrowed,
            returned=returned,
            start_rfids=start_rfids,
            end_rfids=end_tags
        )

        # Record borrow/return history locally
        for item in borrowed:
            self.local_db.record_borrow(
                session_id=self.session_id,
                user_id=self.current_user_id,
                user_name=self.current_user_name,
                rfid_tag=item['rfid'],
                item_id=item.get('item_id'),
                item_name=item.get('name', 'Unknown')
            )

        for item in returned:
            self.local_db.record_return(
                session_id=self.session_id,
                user_id=self.current_user_id,
                user_name=self.current_user_name,
                rfid_tag=item['rfid'],
                item_id=item.get('item_id'),
                item_name=item.get('name', 'Unknown')
            )

        # Display summary (flat payload for display compatibility)
        self._send_to_display({
            'type': 'SESSION_SUMMARY',
            'user_name': self.current_user_name,
            'borrowed': borrowed,
            'returned': returned
        })

        # Try to sync with server
        sync_success = self._try_sync_session(start_rfids, end_tags, borrowed, returned)

        if not sync_success:
            # Queue for later if sync failed
            self.local_db.queue_session_sync(
                session_id=self.session_id,
                user_id=self.current_user_id,
                start_rfids=start_rfids,
                end_rfids=end_tags
            )
            logger.info(f"Session {self.session_id[:8]} queued for later sync")
            self._send_to_display({
                'type': 'SYNC_QUEUED',
                'message': 'Changes saved locally, will sync when online'
            })

        # Cleanup
        self.inventory.end_session()

        # Show summary for 10 seconds then return to locked
        time.sleep(10)
        self.state_machine.transition(SystemState.LOCKED)

    def _try_sync_session(self, start_rfids: list, end_rfids: list,
                         borrowed: list, returned: list) -> bool:
        """
        Try to sync session with server.

        Returns:
            True if successful, False if should queue for later
        """
        if not self.sync_worker.is_online():
            logger.warning("Offline, will retry later")
            return False

        try:
            result = self.api.sync_session(
                session_id=self.session_id,
                cabinet_id=CONFIG['cabinet_id'],
                user_id=self.current_user_id,
                start_rfids=start_rfids,
                end_rfids=end_rfids
            )

            # Validate server result matches local calculation
            server_txs = result.get('transactions', [])
            server_borrowed = len([t for t in server_txs if t.get('action') == 'BORROW'])
            server_returned = len([t for t in server_txs if t.get('action') == 'RETURN'])
            local_borrowed = len(borrowed)
            local_returned = len(returned)

            if server_borrowed == local_borrowed and server_returned == local_returned:
                logger.info(f"Sync confirmed: {server_borrowed} borrowed, {server_returned} returned")
                self.local_db.mark_session_server_confirmed(self.session_id)
            else:
                logger.warning(f"Sync mismatch - Server: {server_borrowed}/{server_returned}, Local: {local_borrowed}/{local_returned}")

            # Mark diff as synced
            self.local_db.mark_diff_synced(self.session_id)

            self._send_to_display({
                'type': 'SYNC_SUCCESS',
                'message': 'Changes synced with server'
            })

            return True

        except APIError as e:
            logger.error(f"Sync failed: {e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected sync error: {e}")
            return False

    # =================================================================================
    # Pairing Mode
    # =================================================================================

    def _handle_pairing_scan(self, card_uid: str):
        """Handle card scan in pairing mode."""
        logger.info(f"Pairing mode: Card {card_uid[:10]}... detected")

        self._send_to_display({
            'type': 'PAIRING_PROMPT',
            'message': 'Show pairing QR code or enter pairing code'
        })

        # Try to read QR code
        qr_content = self.hardware.read_qr(timeout=30)

        if qr_content:
            # Try QR pairing
            result = self.pairing_handler.pair_with_qr(
                qr_content, card_uid, CONFIG['cabinet_id']
            )
            self._handle_pairing_result(result)
        else:
            # Timeout - go back to normal mode
            logger.info("Pairing timeout, returning to normal mode")
            self.mode = self.MODE_NORMAL
            self.state_machine.transition(SystemState.LOCKED)

    def _handle_pairing_result(self, result: PairingResult):
        """Handle pairing result."""
        if result.success:
            logger.info(f"Pairing successful: {result.message}")
            self.hardware.set_all_leds('green')
            self.hardware.beep_success()

            self._send_to_display({
                'type': 'PAIRING_SUCCESS',
                'message': result.message,
                'user_id': result.user_id
            })

            time.sleep(3)
        else:
            logger.warning(f"Pairing failed: {result.message}")
            self.hardware.set_all_leds('red')
            self.hardware.beep_error()

            self._send_to_display({
                'type': 'PAIRING_FAILURE',
                'error': result.message,
                'code': result.error_code
            })

            time.sleep(3)

        # Return to normal mode
        self.mode = self.MODE_NORMAL
        self.state_machine.transition(SystemState.LOCKED)

    def enter_pairing_mode(self):
        """Manually enter pairing mode (for testing or admin use)."""
        logger.info("Entering pairing mode")
        self.mode = self.MODE_PAIRING
        self._send_to_display({
            'type': 'PAIRING_MODE',
            'message': 'Pairing mode active. Tap unpaired card to begin.'
        })

    def _enter_pairing_mode(self, token: str):
        """
        Enter pairing mode from QR scan (QR-first flow).

        Flow:
        1. QR scanned in locked state -> enter pairing mode
        2. Wait for NFC card tap (10s timeout)
        3. Complete pairing via API

        Args:
            token: Pairing token extracted from QR code
        """
        logger.info(f"Entering pairing mode with token: {token}")
        self._pairing_token = token

        self._send_to_display({
            'type': 'PAIRING_MODE',
            'message': 'Pairing mode: Tap NFC card to complete pairing (10s timeout)'
        })
        self.hardware.set_all_leds('yellow')

        # Wait for NFC card tap (10 second timeout)
        start_time = time.time()
        card_uid = None
        card_attempts = []

        while time.time() - start_time < 10:
            card = self.hardware.read_nfc(timeout=0.5)
            if card and len(card) >= 4:  # Validate card UID length (at least 4 chars)
                card_attempts.append(card)
                # If we get the same card twice, accept it
                if len(card_attempts) >= 2 and card_attempts[-1] == card_attempts[-2]:
                    card_uid = card
                    break
                # Or accept immediately if looks like a valid card (numeric/string)
                if len(card) >= 8:
                    card_uid = card
                    break
            time.sleep(0.1)

        if not card_uid:
            logger.info("Pairing timeout - no valid card detected")
            self._send_to_display({
                'type': 'PAIRING_FAILURE',
                'error': 'Timeout - no card detected',
                'code': 'TIMEOUT'
            })
            self.hardware.beep_error()
            time.sleep(2)
            self._send_to_display({
                'type': 'STATE_CHANGE',
                'state': 'IDLE',
                'message': 'Tap card or scan QR code to open'
            })
            return

        logger.info(f"Card detected for pairing: {card_uid[:10]}...")

        # Clean token before sending to API
        clean_token = self.pairing_handler._clean_hid_input(token)
        logger.info(f"Attempting pairing with token: {clean_token}, card: {card_uid}")

        # Complete pairing via API
        result = self.pairing_handler.pair_with_qr(
            qr_content=clean_token,
            card_uid=card_uid,
            cabinet_id=CONFIG['cabinet_id']
        )

        if result.success:
            logger.info(f"Pairing successful: {result.message}")
            self.hardware.set_all_leds('green')
            self.hardware.beep_success()
            self._send_to_display({
                'type': 'PAIRING_SUCCESS',
                'message': result.message,
                'user_id': result.user_id
            })
            time.sleep(3)
        else:
            logger.warning(f"Pairing failed: {result.message}")
            self.hardware.set_all_leds('red')
            self.hardware.beep_error()
            self._send_to_display({
                'type': 'PAIRING_FAILURE',
                'error': result.message,
                'code': result.error_code
            })
            time.sleep(3)

        # Return to idle
        self._send_to_display({
            'type': 'STATE_CHANGE',
            'state': 'IDLE',
            'message': 'Tap card or scan QR code to open'
        })
        self._pairing_token = None

    # =================================================================================
    # RFID Scanning
    # =================================================================================

    def _scan_rfid(self) -> list:
        """
        Perform RFID scan with voting mechanism for accurate results.

        Uses 5 scan cycles and requires a tag to appear at least 2 times
        to be considered present. This reduces false positives from
        sporadic reads.
        """
        logger.info("Starting RFID voting scan (10 cycles, need 3+ appearances)")
        result = self.hardware.read_rfid_tags_voting()
        logger.info(f"RFID voting scan complete: {len(result)} confirmed tags")
        return result

    # =================================================================================
    # Main Loop
    # =================================================================================

    def run(self):
        """Main loop."""
        logger.info("Starting Smart Cabinet main loop")
        self.running = True

        # Initialize hardware
        self.hardware.initialize()

        # Initial state
        self.state_machine.transition(SystemState.LOCKED)

        try:
            while self.running:
                state = self.state_machine.current_state

                if state == SystemState.LOCKED:
                    self._handle_locked()
                elif state == SystemState.AUTHENTICATING:
                    pass  # Handled by on_enter
                elif state == SystemState.UNLOCKED:
                    pass  # Handled by on_enter
                elif state == SystemState.SCANNING:
                    pass  # Handled by on_enter

                time.sleep(0.1)

        except KeyboardInterrupt:
            logger.info("\nUser interrupt")
            self.running = False
        except Exception as e:
            logger.exception("Fatal error in main loop")
        finally:
            self.cleanup()

    def _handle_locked(self):
        """Poll for NFC or QR in LOCKED state."""
        # Skip if hardware not initialized yet
        if not getattr(self.hardware, '_initialized', False):
            return

        # Check for QR code first (pairing mode)
        qr = self.hardware.read_qr(timeout=0.1)
        if qr:
            token = self.pairing_handler.extract_token_from_qr(qr)
            if token:
                logger.info(f"Pairing QR detected: {token}")
                self._enter_pairing_mode(token)
                return

        card = self.hardware.read_nfc(timeout=0.5)
        if card:
            # Check if this is actually a QR code (pairing token) scanned as NFC
            token = self.pairing_handler.extract_token_from_qr(card)
            if token:
                logger.info(f"Pairing token detected via NFC reader: {token}")
                self._enter_pairing_mode(token)
                return

            logger.info(f"Card detected: {card[:10]}...")
            self.current_card_uid = card  # Save so _on_authenticating doesn't re-read
            self.state_machine.transition(SystemState.AUTHENTICATING)

    def cleanup(self):
        """Cleanup resources."""
        logger.info("Cleaning up...")
        self.running = False
        self.sync_worker.stop()
        if self.display:
            try:
                self.display.stop()
                self.display.join(timeout=2)
            except Exception as e:
                logger.debug(f"Display cleanup error: {e}")
        self.local_db.close()
        self.hardware.cleanup()
        logger.info("Cleanup complete")

    def get_stats(self) -> Dict[str, Any]:
        """Get system statistics."""
        return {
            'hardware_mode': 'raspberry_pi',
            'online': self.sync_worker.is_online(),
            'current_state': self.state_machine.current_state.value,
            'current_user': self.current_user_name,
            'db_stats': self.local_db.get_stats()
        }


if __name__ == "__main__":
    cabinet = SmartCabinet()

    # Optional: Print stats on startup
    stats = cabinet.get_stats()
    logger.info(f"System stats: {json.dumps(stats, indent=2, default=str)}")

    cabinet.run()
