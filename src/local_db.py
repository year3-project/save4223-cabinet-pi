"""Local SQLite database for offline operation."""

import sqlite3
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalDB:
    """SQLite database for local caching and offline queue."""
    
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = None
        self._connect()
        self._init_schema()
    
    def _connect(self):
        """Establish database connection."""
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
    
    def _init_schema(self):
        """Initialize database schema."""
        schema = '''
        -- Authentication cache
        CREATE TABLE IF NOT EXISTS auth_cache (
            card_uid TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            user_name TEXT,
            cabinet_id INTEGER,
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        );
        
        -- Item state cache
        CREATE TABLE IF NOT EXISTS item_cache (
            rfid_tag TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            name TEXT,
            status TEXT,
            holder_id TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Pending sync sessions
        CREATE TABLE IF NOT EXISTS pending_sync (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            rfids TEXT,  -- JSON array
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Access logs
        CREATE TABLE IF NOT EXISTS access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_uid TEXT,
            user_id TEXT,
            session_id TEXT,
            tags_found TEXT,  -- JSON array
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Create indexes
        CREATE INDEX IF NOT EXISTS idx_auth_expires ON auth_cache(expires_at);
        CREATE INDEX IF NOT EXISTS idx_pending_created ON pending_sync(created_at);
        '''
        
        self._conn.executescript(schema)
        self._conn.commit()
        logger.info("Database schema initialized")
    
    def cache_auth(self, card_uid: str, auth_result: Dict[str, Any], ttl: int = 3600):
        """Cache successful authentication."""
        expires = datetime.fromtimestamp(datetime.now().timestamp() + ttl)
        
        with self._conn:
            self._conn.execute('''
                INSERT OR REPLACE INTO auth_cache 
                (card_uid, user_id, user_name, cabinet_id, cached_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                card_uid,
                auth_result.get('user_id'),
                auth_result.get('user_name'),
                auth_result.get('cabinet_id'),
                datetime.now(),
                expires
            ))
    
    def get_cached_auth(self, card_uid: str) -> Optional[Dict[str, Any]]:
        """Get cached authentication if not expired."""
        row = self._conn.execute('''
            SELECT * FROM auth_cache 
            WHERE card_uid = ? AND expires_at > ?
        ''', (card_uid, datetime.now())).fetchone()
        
        if row:
            return {
                'authorized': True,
                'user_id': row['user_id'],
                'user_name': row['user_name'],
                'cabinet_id': row['cabinet_id'],
                'source': 'cache'
            }
        return None
    
    def queue_sync_session(self, session_id: str, user_id: str, rfids: List[str]):
        """Queue session for later sync."""
        with self._conn:
            self._conn.execute('''
                INSERT INTO pending_sync (session_id, user_id, rfids)
                VALUES (?, ?, ?)
            ''', (session_id, user_id, json.dumps(rfids)))
        logger.info(f"Queued session {session_id[:8]} for sync")
    
    def get_pending_sync(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get pending sync sessions."""
        rows = self._conn.execute('''
            SELECT * FROM pending_sync 
            ORDER BY created_at ASC LIMIT ?
        ''', (limit,)).fetchall()
        
        return [{
            'id': row['id'],
            'session_id': row['session_id'],
            'user_id': row['user_id'],
            'rfids': json.loads(row['rfids']),
            'created_at': row['created_at'],
        } for row in rows]
    
    def remove_pending_sync(self, sync_id: int):
        """Remove processed sync from queue."""
        with self._conn:
            self._conn.execute('DELETE FROM pending_sync WHERE id = ?', (sync_id,))
    
    def log_access(self, card_uid: Optional[str], user_id: Optional[str],
                   session_id: Optional[str] = None, tags_found: Optional[List[str]] = None):
        """Log access attempt."""
        with self._conn:
            self._conn.execute('''
                INSERT INTO access_logs (card_uid, user_id, session_id, tags_found)
                VALUES (?, ?, ?, ?)
            ''', (card_uid, user_id, session_id, json.dumps(tags_found or [])))
    
    def update_item_state(self, rfid_tag: str, status: str, holder_id: Optional[str]):
        """Update cached item state."""
        with self._conn:
            self._conn.execute('''
                INSERT OR REPLACE INTO item_cache (rfid_tag, status, holder_id, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (rfid_tag, status, holder_id, datetime.now()))
    
    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            logger.info("Database connection closed")
