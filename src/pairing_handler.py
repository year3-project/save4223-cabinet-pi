"""NFC Card pairing handler for Smart Cabinet Pi.

Handles QR code and NFC card pairing with user accounts.
"""

import logging
import re
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

from api_client import APIClient, APIError
from local_db import LocalDB

logger = logging.getLogger(__name__)


@dataclass
class PairingResult:
    """Result of a pairing attempt."""
    success: bool
    message: str
    user_id: Optional[str] = None
    card_uid: Optional[str] = None
    paired_at: Optional[datetime] = None
    error_code: Optional[str] = None


class PairingHandler:
    """
    Handles NFC card pairing with user accounts.

    Supports two pairing methods:
    1. QR Code: User shows QR code containing pairing token
    2. NFC Card Tap: User taps unpaired card, then enters pairing code
    """

    # Regex patterns for pairing tokens
    QR_TOKEN_PATTERN = re.compile(r'^[A-Z0-9]{8}$')  # e.g., "ABC12345"
    PAIRING_CODE_PATTERN = re.compile(r'^\d{6}$')   # e.g., "123456"

    def __init__(self, api_client: APIClient, local_db: LocalDB, cabinet_id: int = 1):
        self.api = api_client
        self.db = local_db
        self.cabinet_id = cabinet_id
        self._pending_pairing: Optional[Dict[str, Any]] = None

    def _clean_hid_input(self, content: str) -> str:
        """Clean HID keyboard input by removing common noise patterns."""
        if not content:
            return ""
        # Remove common HID reader suffixes/prefixes
        noise_patterns = ['MK', 'MOMKM', 'MJ', 'MO', 'KM']
        cleaned = content.strip().upper()
        # Keep removing until no more patterns found
        changed = True
        while changed:
            changed = False
            for pattern in noise_patterns:
                if cleaned.endswith(pattern):
                    cleaned = cleaned[:-len(pattern)]
                    changed = True
                if cleaned.startswith(pattern):
                    cleaned = cleaned[len(pattern):]
                    changed = True
        return cleaned

    def extract_token_from_qr(self, qr_content: str) -> Optional[str]:
        """
        Extract pairing token from QR code content.

        Server generates QR codes containing JSON:
          {"type": "CARD_PAIRING", "token": "K9MNP2QR", "exp": "..."}

        The HID keyboard reader strips all non-alphanumeric characters
        (braces, quotes, colons, etc.) and inserts 'M' noise between
        keystrokes, so clean JSON parsing is only possible if the reader
        outputs full ASCII (some models do). Otherwise the long HID
        output is decoded by stripping M-noise and searching for the
        CARDPAIRING + TOKEN markers.

        Card UIDs are short raw strings (~9 chars) and will never match
        the JSON or long-payload checks, but may match the direct 8-char
        pattern — callers must only invoke this for QR-type inputs.
        """
        if not qr_content:
            return None

        # 1. Try clean JSON on the RAW input first (before any uppercasing).
        #    The HID reader with proper shift-key support outputs valid JSON.
        raw = qr_content.strip()
        if raw.startswith('{'):
            try:
                import json
                data = json.loads(raw)
                if data.get('type') == 'CARD_PAIRING':
                    token = data.get('token', '').upper()
                    if self.QR_TOKEN_PATTERN.match(token):
                        logger.debug(f"Token extracted from raw JSON: {token}")
                        return token
            except (json.JSONDecodeError, AttributeError):
                pass

        # 2. Clean HID input (uppercases + strips noise) for fallback checks.
        cleaned = self._clean_hid_input(qr_content)

        # 3. Direct 8-char token (reader outputs clean token only)
        if self.QR_TOKEN_PATTERN.match(cleaned):
            logger.debug(f"Token extracted directly: {cleaned}")
            return cleaned

        # 4. HID-encoded JSON or URL: special chars stripped, M-noise interspersed.
        #    Card UIDs are short (~9 chars); QR payloads are typically much longer.
        if len(cleaned) >= 20:
            token = self._extract_hid_json_token(cleaned)
            if token:
                return token

            token = self._extract_hid_marker_token(cleaned)
            if token:
                return token

        return None

    def _extract_hid_marker_token(self, raw: str) -> Optional[str]:
        """
        Extract token from HID-encoded QR payloads that include markers.

        Looks for TOKEN/PAIRUP/PAIRING/CODE markers after removing M-noise,
        then returns the next 8 alphanumeric characters.
        """
        stripped = raw.upper().replace('M', '')
        markers = ['TOKEN', 'PAIRUP', 'PAIRING', 'CODE']

        for marker in markers:
            idx = stripped.find(marker)
            if idx < 0:
                continue
            start = idx + len(marker)
            candidate = stripped[start:start + 8]
            if self.QR_TOKEN_PATTERN.match(candidate):
                logger.debug(f"Token extracted from HID marker {marker}: {candidate}")
                return candidate

        # Fallback: if there is exactly one 8-digit sequence, use it.
        matches = re.findall(r'\d{8}', stripped)
        if len(matches) == 1:
            logger.debug(f"Token extracted from HID digits: {matches[0]}")
            return matches[0]

        return None

    def _extract_hid_json_token(self, raw: str) -> Optional[str]:
        """
        Decode a HID-keyboard-encoded JSON QR payload.

        The HID reader drops {, ", :, ,, } and inserts M between keystrokes.
        {"type":"CARD_PAIRING","token":"K9MNP2QR","exp":"..."}
        becomes (M-stripped): TYPECARDPAIRINGTOKENK9MNP2QREXP...

        Strategy: strip all M's, check for CARDPAIRING marker, extract 8
        chars immediately after TOKEN keyword.
        """
        stripped = raw.upper().replace('M', '')

        if 'CARDPAIRING' not in stripped:
            return None

        idx = stripped.find('TOKEN')
        if idx < 0:
            return None

        candidate = stripped[idx + 5:idx + 13]  # 5 = len('TOKEN'), 8 chars
        if self.QR_TOKEN_PATTERN.match(candidate):
            logger.debug(f"Token extracted from HID JSON: {candidate}")
            return candidate

        return None

    def pair_with_qr(self, qr_content: str, card_uid: str,
                     cabinet_id: int) -> PairingResult:
        """
        Pair card using QR code pairing token.

        Flow:
        1. User taps unpaired card on reader
        2. System prompts for pairing
        3. User shows QR code from web app
        4. System extracts token and sends to server

        Args:
            qr_content: QR code content
            card_uid: NFC card UID
            cabinet_id: Cabinet ID

        Returns:
            PairingResult with success status
        """
        token = self.extract_token_from_qr(qr_content)

        if not token:
            return PairingResult(
                success=False,
                message="Invalid QR code format",
                error_code="INVALID_QR"
            )

        logger.info(f"Attempting to pair card {card_uid[:10]}... with token {token}")

        try:
            result = self.api.pair_card(
                pairing_token=token,
                card_uid=card_uid,
                cabinet_id=cabinet_id
            )

            if result.get('success'):
                # Cache the new card locally
                self.db.cache_auth(
                    card_uid=card_uid,
                    auth_result={
                        'user_id': result.get('userId'),
                        'user_name': result.get('userName', 'Unknown'),
                        'cabinet_id': cabinet_id
                    },
                    ttl=86400 * 30  # 30 days
                )

                return PairingResult(
                    success=True,
                    message=result.get('message', 'Card paired successfully'),
                    user_id=result.get('userId'),
                    card_uid=card_uid,
                    paired_at=datetime.now()
                )
            else:
                return PairingResult(
                    success=False,
                    message=result.get('message', 'Pairing failed'),
                    error_code="SERVER_ERROR"
                )

        except APIError as e:
            error_str = str(e).lower()

            if 'expired' in error_str:
                return PairingResult(
                    success=False,
                    message="Pairing code has expired. Please generate a new code.",
                    error_code="EXPIRED"
                )
            elif 'already linked' in error_str:
                return PairingResult(
                    success=False,
                    message="This card is already linked to another account",
                    error_code="ALREADY_LINKED"
                )
            elif 'unauthorized' in error_str:
                return PairingResult(
                    success=False,
                    message="Invalid pairing code",
                    error_code="INVALID_TOKEN"
                )
            else:
                return PairingResult(
                    success=False,
                    message=f"Server error: {e}",
                    error_code="SERVER_ERROR"
                )

    def start_manual_pairing(self, card_uid: str) -> PairingResult:
        """
        Start manual pairing process for unpaired card.

        Flow:
        1. User taps unpaired card
        2. System detects card is not registered
        3. System enters pairing mode
        4. User enters 6-digit pairing code from web app
        5. System completes pairing

        Args:
            card_uid: NFC card UID

        Returns:
            PairingResult indicating next step
        """
        self._pending_pairing = {
            'card_uid': card_uid,
            'started_at': datetime.now()
        }

        return PairingResult(
            success=True,
            message="Please enter the 6-digit pairing code from the web app",
            card_uid=card_uid
        )

    def complete_manual_pairing(self, pairing_code: str,
                                cabinet_id: int) -> PairingResult:
        """
        Complete manual pairing with user-entered code.

        Args:
            pairing_code: 6-digit pairing code
            cabinet_id: Cabinet ID

        Returns:
            PairingResult with success status
        """
        if not self._pending_pairing:
            return PairingResult(
                success=False,
                message="No pending pairing session",
                error_code="NO_PENDING_PAIRING"
            )

        # Validate code format
        if not self.PAIRING_CODE_PATTERN.match(pairing_code):
            return PairingResult(
                success=False,
                message="Invalid pairing code format (must be 6 digits)",
                error_code="INVALID_FORMAT"
            )

        card_uid = self._pending_pairing['card_uid']

        # Convert 6-digit code to token format if needed
        # Server accepts both formats
        token = pairing_code.upper()

        result = self.pair_with_qr(token, card_uid, cabinet_id)

        # Clear pending state
        if result.success:
            self._pending_pairing = None

        return result

    def cancel_pairing(self) -> None:
        """Cancel any pending pairing session."""
        if self._pending_pairing:
            logger.info("Pairing cancelled")
            self._pending_pairing = None

    def is_pairing_pending(self) -> bool:
        """Check if there's a pending pairing session."""
        if not self._pending_pairing:
            return False

        # Check if expired (5 minute timeout)
        started = self._pending_pairing['started_at']
        elapsed = (datetime.now() - started).total_seconds()

        if elapsed > 300:  # 5 minutes
            self._pending_pairing = None
            return False

        return True

    def get_pending_card(self) -> Optional[str]:
        """Get the card UID of pending pairing, if any."""
        if self.is_pairing_pending():
            return self._pending_pairing.get('card_uid')
        return None

    def handle_unpaired_card(self, card_uid: str, cabinet_id: int,
                            mode: str = 'auto') -> PairingResult:
        """
        Handle detection of unpaired card.

        Args:
            card_uid: NFC card UID
            cabinet_id: Cabinet ID
            mode: 'auto' (use QR) or 'manual' (enter code)

        Returns:
            PairingResult indicating next step
        """
        logger.info(f"Unpaired card detected: {card_uid[:10]}...")

        if mode == 'manual':
            return self.start_manual_pairing(card_uid)
        else:
            # Auto mode - prompt for QR scan
            return PairingResult(
                success=True,
                message="Please show the pairing QR code from the web app",
                card_uid=card_uid,
                error_code="NEEDS_QR"  # Not an error, just needs next step
            )

    def queue_offline_pairing(self, card_uid: str, pairing_code: str) -> bool:
        """
        Queue a pairing for later sync when offline.

        Args:
            card_uid: NFC card UID
            pairing_code: Pairing code entered by user

        Returns:
            True if queued successfully
        """
        try:
            self.db.queue_pending_pairing(
                card_uid=card_uid,
                pairing_code=pairing_code,
                created_at=datetime.now()
            )
            logger.info(f"Pairing queued for later sync: {card_uid[:10]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to queue pairing: {e}")
            return False

    def sync_pending_pairings(self) -> Dict[str, Any]:
        """
        Sync all pending pairings with server.

        Returns:
            Summary of sync results
        """
        pending = self.db.get_pending_pairings()
        results = {
            'total': len(pending),
            'success': 0,
            'failed': 0,
            'errors': []
        }

        for pairing in pending:
            try:
                result = self.api.pair_card(
                    pairing_token=pairing['pairing_code'],
                    card_uid=pairing['card_uid'],
                    cabinet_id=self.cabinet_id
                )

                if result.get('success'):
                    self.db.remove_pending_pairing(pairing['id'])
                    results['success'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append({
                        'card_uid': pairing['card_uid'],
                        'error': result.get('message')
                    })

            except APIError as e:
                results['failed'] += 1
                results['errors'].append({
                    'card_uid': pairing['card_uid'],
                    'error': str(e)
                })
                # Don't remove from queue - will retry later

        return results
