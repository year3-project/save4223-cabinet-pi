"""Integration tests for Smart Cabinet Pi.

Tests the complete flow from card tap to session sync.
Uses mock hardware for testing without physical components.
"""

import unittest
import sys
import tempfile
import os
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'display'))

from state_machine import StateMachine, SystemState
from local_db import LocalDB
from api_client import APIClient
from sync_worker import SyncWorker
from hardware import MockHardware


class MockAPIClient:
    """Mock API client for testing."""

    def __init__(self, online=True):
        self.online = online
        self.sync_calls = []
        self.auth_results = {}

    def authorize(self, card_uid, cabinet_id):
        if not self.online:
            raise Exception("Server offline")

        if card_uid in self.auth_results:
            return self.auth_results[card_uid]

        return {'authorized': False, 'reason': 'Card not registered'}

    def sync_session(self, session_id, cabinet_id, user_id, start_rfids=None, end_rfids=None):
        if not self.online:
            raise Exception("Server offline")

        self.sync_calls.append({
            'session_id': session_id,
            'user_id': user_id,
            'start_rfids': start_rfids or [],
            'end_rfids': end_rfids or []
        })

        # Calculate diff
        start_set = set(start_rfids or [])
        end_set = set(end_rfids or [])

        borrowed = [{'rfid': tag, 'action': 'BORROW'} for tag in start_set - end_set]
        returned = [{'rfid': tag, 'action': 'RETURN'} for tag in end_set - start_set]

        return {
            'success': True,
            'transactions': borrowed + returned,
            'summary': {
                'borrowed': len(borrowed),
                'returned': len(returned)
            }
        }

    def health_check(self):
        return self.online

    def set_auth_result(self, card_uid, result):
        self.auth_results[card_uid] = result


class TestFullSessionFlow(unittest.TestCase):
    """Test complete session flow."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'
        self.db = LocalDB(str(self.db_path))
        self.hardware = MockHardware()
        self.api = MockAPIClient(online=True)
        self.sync_worker = SyncWorker(self.db, self.api, interval=1)

        # Set up mock auth
        self.api.set_auth_result('CARD-001', {
            'authorized': True,
            'user_id': 'user-001',
            'user_name': 'Test User',
            'session_id': 'test-session'
        })

    def tearDown(self):
        """Clean up."""
        self.sync_worker.stop()
        self.db.close()
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_offline_auth_with_cache(self):
        """Test authentication works offline with cached credentials."""
        # First, cache the auth
        self.db.cache_auth('CARD-002', {
            'user_id': 'user-002',
            'user_name': 'Cached User',
            'authorized': True
        }, ttl=3600)

        # Go offline
        self.api.online = False

        # Should still authenticate from cache
        cached = self.db.get_cached_auth('CARD-002')
        self.assertIsNotNone(cached)
        self.assertEqual(cached['user_id'], 'user-002')

    def test_session_diff_calculation(self):
        """Test calculating session diff from RFID snapshots."""
        # Simulate previous session
        self.db.save_rfid_snapshot('prev-session', 1, ['RFID-001', 'RFID-002', 'RFID-003'], 'end')

        # Current session
        self.db.save_rfid_snapshot('curr-session', 1, ['RFID-002', 'RFID-003', 'RFID-004'], 'start')
        self.db.save_rfid_snapshot('curr-session', 1, ['RFID-002', 'RFID-004'], 'end')

        # Calculate diff
        start = self.db.get_snapshot('curr-session', 'start')
        end = self.db.get_snapshot('curr-session', 'end')

        borrowed = set(start) - set(end)  # RFID-003
        returned = set(end) - set(start)  # None

        self.assertIn('RFID-003', borrowed)
        self.assertEqual(len(returned), 0)

    def test_sync_queue_processing(self):
        """Test pending sync queue is processed."""
        # Queue a session
        self.db.queue_session_sync(
            session_id='pending-001',
            user_id='user-001',
            start_rfids=['RFID-001', 'RFID-002'],
            end_rfids=['RFID-002']
        )

        # Start sync worker
        self.sync_worker.start()

        # Wait for sync
        time.sleep(2)

        # Check sync was attempted
        self.assertEqual(len(self.api.sync_calls), 1)
        self.assertEqual(self.api.sync_calls[0]['session_id'], 'pending-001')

    def test_offline_queue_behavior(self):
        """Test queue behavior when offline."""
        # Go offline
        self.api.online = False

        # Queue a session
        self.db.queue_session_sync(
            session_id='offline-001',
            user_id='user-001',
            start_rfids=['RFID-001'],
            end_rfids=['RFID-002']
        )

        # Start sync worker
        self.sync_worker.start()

        # Wait
        time.sleep(2)

        # Should not have synced (offline)
        self.assertEqual(len(self.api.sync_calls), 0)

        # Pending should still be there
        pending = self.db.get_pending_sync_full()
        self.assertEqual(len(pending), 1)

    def test_idempotency(self):
        """Test sync queue idempotency."""
        # Queue same session twice
        result1 = self.db.queue_session_sync('dup-001', 'user-001', ['A'], ['B'])
        result2 = self.db.queue_session_sync('dup-001', 'user-001', ['A'], ['B'])

        self.assertTrue(result1)
        self.assertFalse(result2)  # Second should fail (already queued)

        # Only one in queue
        pending = self.db.get_pending_sync_full()
        self.assertEqual(len(pending), 1)


class TestMockHardware(unittest.TestCase):
    """Test mock hardware implementation."""

    def setUp(self):
        self.hw = MockHardware(num_drawers=4, num_leds=8)

    def test_initialization(self):
        """Test mock hardware initializes."""
        self.hw.initialize()
        self.assertTrue(self.hw._initialized)

    def test_drawer_lock_unlock(self):
        """Test drawer lock/unlock."""
        self.hw.unlock_drawer(0)
        self.assertEqual(self.hw.get_drawer_state(0).value, 'open')

        self.hw.lock_drawer(0)
        self.assertEqual(self.hw.get_drawer_state(0).value, 'closed')

    def test_all_drawers_closed(self):
        """Test checking all drawers closed."""
        self.hw.unlock_all()
        self.assertFalse(self.hw.are_all_drawers_closed())

        self.hw.lock_all()
        self.assertTrue(self.hw.are_all_drawers_closed())

    def test_led_control(self):
        """Test LED control."""
        from hardware import LEDColor

        self.hw.set_led(0, LEDColor.GREEN)
        self.assertEqual(self.hw._led_states[0][0], LEDColor.GREEN)

        self.hw.set_all_leds(LEDColor.RED)
        for i in range(self.hw.num_leds):
            self.assertEqual(self.hw._led_states[i][0], LEDColor.RED)


class TestStateTransitions(unittest.TestCase):
    """Test state machine transitions in context."""

    def setUp(self):
        self.sm = StateMachine()

        # Define allowed transitions
        self.sm.allow_transition(SystemState.LOCKED, [SystemState.AUTHENTICATING])
        self.sm.allow_transition(SystemState.AUTHENTICATING, [SystemState.UNLOCKED, SystemState.LOCKED])
        self.sm.allow_transition(SystemState.UNLOCKED, [SystemState.SCANNING])
        self.sm.allow_transition(SystemState.SCANNING, [SystemState.LOCKED])

    def test_normal_flow(self):
        """Test normal operation flow."""
        states_visited = []

        def record_state(ctx):
            states_visited.append(self.sm.current_state)

        for state in SystemState:
            self.sm.on_enter(state, record_state)

        # Normal flow
        self.sm.transition(SystemState.AUTHENTICATING)
        self.sm.transition(SystemState.UNLOCKED)
        self.sm.transition(SystemState.SCANNING)
        self.sm.transition(SystemState.LOCKED)

        self.assertEqual(self.sm.current_state, SystemState.LOCKED)

    def test_auth_failure_flow(self):
        """Test flow when authentication fails."""
        self.sm.transition(SystemState.AUTHENTICATING)
        self.sm.transition(SystemState.LOCKED)  # Back to locked on failure

        self.assertEqual(self.sm.current_state, SystemState.LOCKED)


if __name__ == '__main__':
    unittest.main()
