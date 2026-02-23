"""API client for Save4223 backend."""

import requests
import logging
from typing import Optional, Dict, Any
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


class APIError(Exception):
    """API request error."""
    pass


class APIClient:
    """HTTP client for Save4223 Edge API."""
    
    def __init__(self, base_url: str, edge_secret: str, timeout: int = 5):
        self.base_url = base_url.rstrip('/')
        self.edge_secret = edge_secret
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {edge_secret}',
            'Content-Type': 'application/json',
        })
    
    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with error handling."""
        url = urljoin(self.base_url + '/', path.lstrip('/'))
        
        try:
            response = self.session.request(
                method=method,
                url=url,
                timeout=self.timeout,
                **kwargs
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            raise APIError("Request timeout")
        except requests.exceptions.ConnectionError:
            raise APIError("Connection failed")
        except requests.exceptions.HTTPError as e:
            raise APIError(f"HTTP {e.response.status_code}: {e.response.text}")
        except Exception as e:
            raise APIError(f"Request failed: {e}")
    
    def authorize(self, card_uid: str, cabinet_id: int) -> Dict[str, Any]:
        """
        Authenticate card UID with server.
        
        POST /api/edge/authorize
        """
        logger.debug(f"Authorizing card: {card_uid[:10]}...")
        
        result = self._request('POST', '/api/edge/authorize', json={
            'card_uid': card_uid,
            'cabinet_id': cabinet_id,
        })
        
        return result
    
    def sync_session(self, session_id: str, cabinet_id: int, 
                     user_id: str, rfids: list) -> Dict[str, Any]:
        """
        Sync RFID scan results with server.
        
        POST /api/edge/sync-session
        """
        logger.debug(f"Syncing session: {session_id[:8]}... with {len(rfids)} tags")
        
        result = self._request('POST', '/api/edge/sync-session', json={
            'session_id': session_id,
            'cabinet_id': cabinet_id,
            'user_id': user_id,
            'rfids_present': rfids,
        })
        
        return result
    
    def local_sync(self, cabinet_id: int) -> Dict[str, Any]:
        """
        Get local sync data (cached auth and items).
        
        GET /api/edge/local-sync
        """
        logger.debug(f"Fetching local sync data for cabinet {cabinet_id}")
        
        result = self._request('GET', '/api/edge/local-sync', params={
            'cabinet_id': cabinet_id,
        })
        
        return result
    
    def health_check(self) -> bool:
        """Check if server is reachable."""
        try:
            self._request('GET', '/api/health')
            return True
        except APIError:
            return False
    
    def pair_card(self, pairing_token: str, card_uid: str, cabinet_id: int) -> Dict[str, Any]:
        """
        Pair an NFC card with a user using a pairing token.
        
        POST /api/edge/pair-card
        """
        logger.debug(f"Pairing card: {card_uid[:10]}... with token")
        
        result = self._request('POST', '/api/edge/pair-card', json={
            'pairing_token': pairing_token,
            'card_uid': card_uid,
            'cabinet_id': cabinet_id,
        })
        
        return result
