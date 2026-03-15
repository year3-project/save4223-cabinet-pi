"""Unit tests for local database."""

import unittest
import sys
import tempfile
import os
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from local_db import LocalDB


class TestLocalDB(unittest.TestCase):
    """Test LocalDB functionality."""

    def setUp(self):
        """Set up test database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'
        self.db = LocalDB(str(self.db_path))

    def tearDown(self):
        """Clean up test database."""
        self.db.close()
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_initialization(self):
        """Test database initializes correctly."""
        self.assertTrue(self.db_path.exists())
        stats = self.db.get_stats()
        self.assertIn('pending_syncs', stats)

    def test_cache_auth(self):
        """Test caching authentication."""
        auth_result = {
            'user_id': 'user-123',
            'user_name': 'Test User',
            'cabinet_id': 1
        }

        self.db.cache_auth('card-001', auth_result, ttl=3600)
        cached = self.db.get_cached_auth('card-001')

        self.assertIsNotNone(cached)
        self.assertEqual(cached['user_id'], 'user-123')
        self.assertEqual(cached['source'], 'cache')

    def test_cache_auth_expiration(self):
        """Test cached auth expires correctly."""
        auth_result = {'user_id': 'user-123', 'user_name': 'Test User'}

        # Cache with very short TTL
        self.db.cache_auth('card-002', auth_result, ttl=-1)

        # Should be expired immediately
        cached = self.db.get_cached_auth('card-002')
        self.assertIsNone(cached)

    def test_rfid_snapshot(self):
        """Test saving and retrieving RFID snapshots."""
        session_id = 'session-001'
        cabinet_id = 1
        tags = ['RFID-001', 'RFID-002', 'RFID-003']

        self.db.save_rfid_snapshot(session_id, cabinet_id, tags, 'end')
        retrieved = self.db.get_snapshot(session_id, 'end')

        self.assertEqual(set(retrieved), set(tags))

    def test_snapshot_start_and_end(self):
        """Test saving both start and end snapshots."""
        session_id = 'session-002'
        start_tags = ['RFID-001', 'RFID-002']
        end_tags = ['RFID-002', 'RFID-003']

        self.db.save_rfid_snapshot(session_id, 1, start_tags, 'start')
        self.db.save_rfid_snapshot(session_id, 1, end_tags, 'end')

        self.assertEqual(set(self.db.get_snapshot(session_id, 'start')), set(start_tags))
        self.assertEqual(set(self.db.get_snapshot(session_id, 'end')), set(end_tags))

    def test_get_last_snapshot(self):
        """Test getting last snapshot from previous session."""
        # First session
        self.db.save_rfid_snapshot('session-old', 1, ['RFID-001', 'RFID-002'], 'end')

        # Current session
        self.db.save_rfid_snapshot('session-new', 1, ['RFID-002', 'RFID-003'], 'start')

        # Get last snapshot (should be from session-old)
        last = self.db.get_last_snapshot(1, before_session='session-new')
        self.assertEqual(set(last), {'RFID-001', 'RFID-002'})

    def test_session_diff(self):
        """Test saving and retrieving session diffs."""
        borrowed = [{'rfid': 'RFID-001', 'name': 'Tool 1'}]
        returned = [{'rfid': 'RFID-002', 'name': 'Tool 2'}]

        self.db.save_session_diff(
            session_id='session-003',
            user_id='user-123',
            user_name='Test User',
            borrowed=borrowed,
            returned=returned,
            start_rfids=['RFID-001', 'RFID-002'],
            end_rfids=['RFID-002', 'RFID-003']
        )

        diff = self.db.get_session_full_diff('session-003')

        self.assertIsNotNone(diff)
        self.assertEqual(len(diff['borrowed']), 1)
        self.assertEqual(len(diff['returned']), 1)
        self.assertEqual(diff['user_name'], 'Test User')

    def test_queue_session_sync(self):
        """Test queueing session for sync."""
        result = self.db.queue_session_sync(
            session_id='session-004',
            user_id='user-123',
            start_rfids=['RFID-001'],
            end_rfids=['RFID-002']
        )

        self.assertTrue(result)

        # Should not allow duplicate
        result2 = self.db.queue_session_sync(
            session_id='session-004',
            user_id='user-123',
            start_rfids=['RFID-001'],
            end_rfids=['RFID-002']
        )
        self.assertFalse(result2)

    def test_pending_sync(self):
        """Test getting pending sync items."""
        self.db.queue_session_sync(
            session_id='session-005',
            user_id='user-123',
            start_rfids=['RFID-001'],
            end_rfids=['RFID-002']
        )

        pending = self.db.get_pending_sync_full(limit=10)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['session_id'], 'session-005')

    def test_remove_pending_sync(self):
        """Test removing processed sync."""
        self.db.queue_session_sync(
            session_id='session-006',
            user_id='user-123',
            start_rfids=['RFID-001'],
            end_rfids=['RFID-002']
        )

        pending = self.db.get_pending_sync_full(limit=10)
        self.db.remove_pending_sync(pending[0]['id'])

        pending = self.db.get_pending_sync_full(limit=10)
        self.assertEqual(len(pending), 0)

    def test_access_logs(self):
        """Test access logging."""
        self.db.log_access(
            card_uid='card-001',
            user_id='user-123',
            user_name='Test User',
            session_id='session-007',
            action='AUTH_SUCCESS',
            tags_found=['RFID-001']
        )

        logs = self.db.get_access_logs(user_id='user-123')
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['action'], 'AUTH_SUCCESS')

    def test_item_cache(self):
        """Test item cache operations."""
        self.db.update_item_cache(
            rfid_tag='RFID-001',
            item_id='item-001',
            name='Test Tool',
            status='AVAILABLE',
            cabinet_id=1
        )

        item = self.db.get_item_cache('RFID-001')
        self.assertIsNotNone(item)
        self.assertEqual(item['name'], 'Test Tool')
        self.assertEqual(item['status'], 'AVAILABLE')

    def test_borrow_return_history(self):
        """Test recording borrow/return history."""
        self.db.record_borrow(
            session_id='session-008',
            user_id='user-123',
            user_name='Test User',
            rfid_tag='RFID-001',
            item_id='item-001',
            item_name='Test Tool'
        )

        self.db.record_return(
            session_id='session-008',
            user_id='user-123',
            user_name='Test User',
            rfid_tag='RFID-002',
            item_id='item-002',
            item_name='Another Tool'
        )

        history = self.db.get_user_borrow_history('user-123')
        self.assertEqual(len(history), 2)

    def test_offline_queue(self):
        """Test offline action queue."""
        self.db.queue_offline_action(
            action_type='session_sync',
            payload={'session_id': 'test'},
            priority=1
        )

        queue = self.db.get_offline_queue(action_type='session_sync')
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]['action_type'], 'session_sync')

    def test_stats(self):
        """Test getting database statistics."""
        stats = self.db.get_stats()

        required_keys = [
            'pending_syncs', 'pending_pairings', 'offline_queue',
            'items_in_cabinet', 'items_borrowed', 'total_access_logs',
            'cached_users'
        ]

        for key in required_keys:
            self.assertIn(key, stats)


if __name__ == '__main__':
    unittest.main()
