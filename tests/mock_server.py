#!/usr/bin/env python3
"""
Mock Save4223 API Server for testing Pi controller.
Run this locally to simulate the cloud backend.
"""

import json
import uuid
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock data
MOCK_CARDS = {
    "TEST123": {
        "user_id": "550e8400-e29b-41d4-a716-446655440001",
        "user_name": "Test User",
        "email": "test@example.com",
    },
    "CARD456": {
        "user_id": "b6961f07-e43a-4304-ab75-dc51c0b58ce5",
        "user_name": "Vicky",
        "email": "vicky@example.com",
    }
}

MOCK_ITEMS = {
    "RFID-OSC-001": {"id": "item-1", "name": "Oscilloscope #1", "status": "BORROWED", "holder": "550e8400-e29b-41d4-a716-446655440001"},
    "RFID-OSC-002": {"id": "item-2", "name": "Oscilloscope #2", "status": "AVAILABLE", "holder": None},
    "RFID-OSC-003": {"id": "item-3", "name": "Oscilloscope #3", "status": "AVAILABLE", "holder": None},
    "RFID-TOOL-001": {"id": "item-4", "name": "Screwdriver Set", "status": "AVAILABLE", "holder": None},
    "RFID-MUL-001": {"id": "item-5", "name": "Multimeter #1", "status": "BORROWED", "holder": "550e8400-e29b-41d4-a716-446655440001"},
    "RFID-MUL-002": {"id": "item-6", "name": "Multimeter #2", "status": "AVAILABLE", "holder": None},
}


class MockHandler(BaseHTTPRequestHandler):
    """HTTP request handler for mock API."""
    
    def log_message(self, format, *args):
        """Override to use our logger."""
        logger.info(f"{self.address_string()} - {format % args}")
    
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.end_headers()
    
    def do_OPTIONS(self):
        self._set_headers()
    
    def _check_auth(self):
        """Check Bearer token."""
        auth_header = self.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return False
        token = auth_header[7:]
        return token == "edge_device_secret_key"
    
    def _read_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length:
            return json.loads(self.rfile.read(content_length))
        return {}
    
    def do_GET(self):
        """Handle GET requests."""
        if not self._check_auth():
            self._set_headers(401)
            self.wfile.write(json.dumps({"error": "Unauthorized"}).encode())
            return
        
        if self.path.startswith('/api/health'):
            self._set_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        
        elif self.path.startswith('/api/edge/local-sync'):
            # Return mock cached data
            self._set_headers()
            response = {
                "cards": [
                    {"card_uid": uid, "user_id": data["user_id"], "permissions": [1]}
                    for uid, data in MOCK_CARDS.items()
                ],
                "items": [
                    {"rfid_tag": tag, "item_id": data["id"], "name": data["name"]}
                    for tag, data in MOCK_ITEMS.items()
                ]
            }
            self.wfile.write(json.dumps(response).encode())
        
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode())
    
    def do_POST(self):
        """Handle POST requests."""
        if not self._check_auth():
            self._set_headers(401)
            self.wfile.write(json.dumps({"error": "Unauthorized"}).encode())
            return
        
        body = self._read_body()
        
        if self.path.startswith('/api/edge/authorize'):
            # Card authorization
            card_uid = body.get('card_uid', '')
            cabinet_id = body.get('cabinet_id', 1)
            
            if card_uid in MOCK_CARDS:
                user = MOCK_CARDS[card_uid]
                self._set_headers()
                response = {
                    "authorized": True,
                    "session_id": str(uuid.uuid4()),
                    "user_id": user["user_id"],
                    "user_name": user["user_name"],
                    "cabinet_name": f"Cabinet {cabinet_id}"
                }
                logger.info(f"✅ Auth success: {user['user_name']} ({card_uid})")
            else:
                self._set_headers(403)
                response = {
                    "authorized": False,
                    "reason": "Card not registered"
                }
                logger.warning(f"❌ Auth failed: {card_uid}")
            
            self.wfile.write(json.dumps(response).encode())
        
        elif self.path.startswith('/api/edge/sync-session'):
            # Session sync - calculate diff
            session_id = body.get('session_id', '')
            user_id = body.get('user_id', '')
            rfids_present = set(body.get('rfids_present', []))
            
            borrowed = []
            returned = []
            
            for tag, item in MOCK_ITEMS.items():
                is_present = tag in rfids_present
                was_borrowed = item["holder"] == user_id
                
                # Item was borrowed (was present, now gone)
                if was_borrowed and not is_present:
                    borrowed.append({
                        "rfid": tag,
                        "item_id": item["id"],
                        "name": item["name"]
                    })
                    # Update mock state
                    item["status"] = "BORROWED"
                    item["holder"] = user_id
                
                # Item was returned (wasn't here, now present)
                elif item["holder"] and item["holder"] != user_id and is_present:
                    returned.append({
                        "rfid": tag,
                        "item_id": item["id"],
                        "name": item["name"]
                    })
                    # Update mock state
                    item["status"] = "AVAILABLE"
                    item["holder"] = None
            
            self._set_headers()
            response = {
                "borrowed": borrowed,
                "returned": returned,
                "unexpected": [],
                "session_id": session_id
            }
            logger.info(f"📦 Sync: {len(borrowed)} borrowed, {len(returned)} returned")
            self.wfile.write(json.dumps(response).encode())
        
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode())


def run_mock_server(port=3001):
    """Run the mock API server."""
    server = HTTPServer(('localhost', port), MockHandler)
    logger.info(f"🚀 Mock Save4223 API server running on http://localhost:{port}")
    logger.info(f"   Endpoints:")
    logger.info(f"   - POST /api/edge/authorize")
    logger.info(f"   - POST /api/edge/sync-session")
    logger.info(f"   - GET  /api/edge/local-sync")
    logger.info(f"   - GET  /api/health")
    logger.info(f"")
    logger.info(f"   Test cards: {list(MOCK_CARDS.keys())}")
    logger.info(f"   Press Ctrl+C to stop")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("\n👋 Shutting down mock server")
        server.shutdown()


if __name__ == "__main__":
    run_mock_server()
