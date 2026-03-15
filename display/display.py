"""NiceGUI-based display for Smart Cabinet Pi.

Pure Python web UI - no npm/Electron needed.
Runs in browser with live WebSocket updates.
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

try:
    from nicegui import ui, app
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    logging.warning("nicegui not installed. Display will be disabled.")

logger = logging.getLogger(__name__)


class CabinetDisplayGUI:
    """NiceGUI display for cabinet."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080, fullscreen: bool = True):
        """Initialize display.

        Args:
            host: Host to bind to
            port: Port to serve on
            fullscreen: Whether to launch in fullscreen/kiosk mode
        """
        if not NICEGUI_AVAILABLE:
            raise ImportError("nicegui is required. Install with: pip install nicegui")

        self.host = host
        self.port = port
        self.fullscreen = fullscreen

        # Current state
        self.current_state = "LOCKED"
        self.current_user: Optional[Dict] = None
        self.status_message = "Tap card to begin"
        self.session_summary = {}
        self.stats = {}

        # UI elements (initialized in setup)
        self.state_indicator = None
        self.status_label = None
        self.user_card = None
        self.items_container = None
        self.stats_label = None
        self.page = None

        # Track connected clients for broadcasting
        self.clients = set()

    def setup(self):
        """Set up the UI."""

        @ui.page('/')
        def main_page():
            """Main display page."""
            self.page = ui.page

            # Add client to tracking
            client_id = ui.context.client.id
            self.clients.add(client_id)

            # Page styling
            ui.add_head_html('''
                <style>
                    body {
                        margin: 0;
                        padding: 0;
                        background: #121212;
                        color: white;
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        overflow: hidden;
                    }
                    .locked { --status-color: #ef5350; }
                    .unlocked { --status-color: #66bb6a; }
                    .authenticating { --status-color: #ffca28; }
                    .scanning { --status-color: #ffca28; }
                    .pairing { --status-color: #42a5f5; }
                </style>
            ''')

            # Main container
            with ui.column().classes('w-full h-screen items-center justify-center locked').style(
                'background: linear-gradient(135deg, #1e1e1e 0%, #121212 100%);'
            ) as container:

                # Status indicator (large pulsing circle)
                with ui.element('div').style('position: relative; width: 150px; height: 150px;'):
                    # Glow effect
                    ui.element('div').style('''
                        position: absolute;
                        width: 150px;
                        height: 150px;
                        border-radius: 50%;
                        background: var(--status-color);
                        opacity: 0.3;
                        animation: pulse 2s infinite;
                    ''')
                    # Core circle
                    self.state_indicator = ui.element('div').style('''
                        position: absolute;
                        width: 100px;
                        height: 100px;
                        border-radius: 50%;
                        background: var(--status-color);
                        top: 25px;
                        left: 25px;
                    ''')

                # Status title
                self.status_title = ui.label('LOCKED').style('''
                    font-size: 48px;
                    font-weight: bold;
                    color: var(--status-color);
                    margin-top: 30px;
                ''')

                # Status message
                self.status_label = ui.label(self.status_message).style('''
                    font-size: 24px;
                    color: #ffffff;
                    margin-top: 20px;
                    text-align: center;
                    max-width: 600px;
                ''')

                # User card (hidden by default, shown when authenticated)
                with ui.card().classes('w-96 mt-8').style('display: none; background: #2a2a2a;') as self.user_card:
                    with ui.row().classes('items-center'):
                        ui.icon('person').style('font-size: 48px; color: #66bb6a;')
                        with ui.column():
                            self.user_name_label = ui.label('').style('font-size: 24px; font-weight: bold;')
                            self.user_email_label = ui.label('').style('font-size: 16px; color: #aaa;')

                # Session summary (shown after session)
                with ui.card().classes('w-96 mt-8').style('display: none; background: #2a2a2a;') as self.summary_card:
                    ui.label('Session Summary').style('font-size: 20px; font-weight: bold; margin-bottom: 10px;')

                    with ui.column() as self.borrowed_list:
                        ui.label('Borrowed:').style('color: #66bb6a;')

                    with ui.column() as self.returned_list:
                        ui.label('Returned:').style('color: #42a5f5;')

                # Stats at bottom
                self.stats_label = ui.label('').style('''
                    position: fixed;
                    bottom: 20px;
                    right: 20px;
                    font-size: 14px;
                    color: #666;
                ''')

                # Add pulse animation
                ui.add_head_html('''
                    <style>
                        @keyframes pulse {
                            0%, 100% { transform: scale(1); opacity: 0.3; }
                            50% { transform: scale(1.1); opacity: 0.5; }
                        }
                    </style>
                ''')

            # Auto-refresh stats
            ui.timer(5.0, self._update_stats_ui)

            # Cleanup on disconnect
            def on_disconnect():
                self.clients.discard(client_id)
            ui.context.client.on_disconnect(on_disconnect)

    def _update_stats_ui(self):
        """Update stats display."""
        if self.stats_label:
            stats_text = f"State: {self.current_state} | {datetime.now().strftime('%H:%M')}"
            self.stats_label.text = stats_text

    def update_state(self, state: str, message: str = ""):
        """Update display state.

        Args:
            state: New state (LOCKED, AUTHENTICATING, UNLOCKED, SCANNING, PAIRING, SUMMARY)
            message: Status message to display
        """
        self.current_state = state
        if message:
            self.status_message = message

        # Broadcast to all connected clients
        for client_id in list(self.clients):
            try:
                ui.run_javascript(f'''
                    document.body.className = 'w-full h-screen items-center justify-center {state.lower()}';
                ''', client_id=client_id)
            except Exception:
                pass

        # Update UI elements
        if state == "LOCKED":
            self._update_ui_elements(
                title="LOCKED",
                message=self.status_message or "Tap card to unlock",
                show_user=False,
                show_summary=False
            )
        elif state == "AUTHENTICATING":
            self._update_ui_elements(
                title="Reading Card...",
                message=self.status_message or "Please wait",
                show_user=False,
                show_summary=False
            )
        elif state == "UNLOCKED":
            user_name = self.current_user.get("name", "User") if self.current_user else "User"
            self._update_ui_elements(
                title="UNLOCKED",
                message=self.status_message or f"Welcome, {user_name}!",
                show_user=True,
                show_summary=False
            )
        elif state == "SCANNING":
            self._update_ui_elements(
                title="Scanning...",
                message=self.status_message or "Checking inventory",
                show_user=True,
                show_summary=False
            )
        elif state == "PAIRING":
            self._update_ui_elements(
                title="Pairing Mode",
                message=self.status_message or "Show QR code to pair card",
                show_user=False,
                show_summary=False
            )
        elif state == "SUMMARY":
            self._update_ui_elements(
                title="Session Complete",
                message=self.status_message or "Thank you!",
                show_user=True,
                show_summary=True
            )

    def _update_ui_elements(self, title: str, message: str, show_user: bool, show_summary: bool):
        """Update UI element contents."""
        if self.status_title:
            self.status_title.text = title
        if self.status_label:
            self.status_label.text = message

        # Update user card
        if self.user_card:
            if show_user and self.current_user:
                self.user_card.style('display: block;')
                self.user_name_label.text = self.current_user.get("name", "")
                self.user_email_label.text = self.current_user.get("email", "")
            else:
                self.user_card.style('display: none;')

        # Update summary
        if self.summary_card:
            if show_summary:
                self.summary_card.style('display: block;')
                self._update_summary_lists()
            else:
                self.summary_card.style('display: none;')

    def _update_summary_lists(self):
        """Update borrowed/returned lists."""
        borrowed = self.session_summary.get("borrowed", [])
        returned = self.session_summary.get("returned", [])

        # Clear and rebuild lists
        self.borrowed_list.clear()
        with self.borrowed_list:
            ui.label(f"Borrowed ({len(borrowed)}):").style('color: #66bb6a; font-weight: bold;')
            for item in borrowed:
                name = item.get("name", "Unknown")
                ui.label(f"• {name}").style('margin-left: 10px;')

        self.returned_list.clear()
        with self.returned_list:
            ui.label(f"Returned ({len(returned)}):").style('color: #42a5f5; font-weight: bold;')
            for item in returned:
                name = item.get("name", "Unknown")
                ui.label(f"• {name}").style('margin-left: 10px;')

    def handle_message(self, message: Dict[str, Any]):
        """Handle message from main app."""
        msg_type = message.get("type", "")

        if msg_type == "STATE_CHANGE":
            self.update_state(
                message.get("state", "LOCKED"),
                message.get("message", "")
            )

        elif msg_type == "AUTH_SUCCESS":
            self.current_user = message.get("user", {})
            self.update_state("UNLOCKED")

        elif msg_type == "AUTH_FAILURE":
            self.status_message = message.get("error", "Access denied")
            self.update_state("LOCKED", self.status_message)

        elif msg_type == "SESSION_SUMMARY":
            self.session_summary = message.get("summary", {})
            self.current_user = {"name": message.get("user_name", "User")}
            self.update_state("SUMMARY")

        elif msg_type == "SYNC_SUCCESS":
            self.status_message = message.get("message", "Synced")
            self.update_state("SUMMARY", self.status_message)

        elif msg_type == "SYNC_QUEUED":
            self.status_message = message.get("message", "Saved locally")
            self.update_state("SUMMARY", self.status_message)

        elif msg_type == "PAIRING_MODE":
            self.update_state("PAIRING", message.get("message", ""))

        elif msg_type == "PAIRING_SUCCESS":
            self.status_message = message.get("message", "Card paired!")
            self.update_state("LOCKED", self.status_message)

        elif msg_type == "WARNING":
            self.status_message = message.get("message", "")
            # Keep current state, just update message
            self.update_state(self.current_state, self.status_message)

    def run(self):
        """Run the display (blocking)."""
        self.setup()

        # Open browser in fullscreen/kiosk mode if requested
        if self.fullscreen:
            import webbrowser
            import subprocess
            import time

            def open_kiosk():
                time.sleep(2)  # Wait for server to start
                try:
                    # Try chromium in kiosk mode (Raspberry Pi)
                    subprocess.Popen([
                        'chromium-browser',
                        f'http://localhost:{self.port}',
                        '--kiosk',
                        '--noerrdialogs',
                        '--disable-infobars',
                        '--check-for-update-interval=31536000'
                    ])
                except FileNotFoundError:
                    try:
                        # Fallback to regular chrome/chromium
                        subprocess.Popen([
                            'google-chrome',
                            f'http://localhost:{self.port}',
                            '--kiosk',
                            '--app'
                        ])
                    except FileNotFoundError:
                        # Last resort: default browser
                        webbrowser.open(f'http://localhost:{self.port}')

            import threading
            threading.Thread(target=open_kiosk, daemon=True).start()

        # Start NiceGUI
        ui.run(
            host=self.host,
            port=self.port,
            title="Smart Cabinet",
            favicon="🔐",
            reload=False,
            show=False  # Don't auto-open browser (we do it ourselves)
        )

    def run_in_thread(self):
        """Run display in background thread."""
        import threading
        # Setup must be called in main thread before starting server thread
        self.setup()
        thread = threading.Thread(target=self._run_server, daemon=True)
        thread.start()
        return thread

    def _run_server(self):
        """Internal: run just the server without blocking."""
        import uvicorn
        # Don't call setup() again - it was already called in run_in_thread
        # Just run uvicorn with the already-configured app
        uvicorn.run(
            app,
            host=self.host,
            port=self.port,
            log_level="warning",
            loop="asyncio"
        )


class DisplayThread:
    """Thread wrapper for NiceGUI display (compatible interface)."""

    def __init__(self, width: int = 800, height: int = 480, fullscreen: bool = True):
        self.display = CabinetDisplayGUI(
            host="0.0.0.0",
            port=8080,
            fullscreen=fullscreen
        )
        self._thread = None

    def start(self):
        """Start display in thread."""
        import threading
        self._thread = threading.Thread(target=self.display.run_in_thread, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the display."""
        # NiceGUI doesn't have a clean shutdown, but the thread is daemon
        pass

    def join(self, timeout: float = None):
        """Join thread (no-op for daemon thread)."""
        if self._thread:
            self._thread.join(timeout=timeout)

    def send_message(self, message: Dict[str, Any]):
        """Send message to display."""
        # Schedule on NiceGUI's event loop
        if NICEGUI_AVAILABLE:
            ui.timer(0.1, lambda: self.display.handle_message(message), once=True)


# Standalone test
if __name__ == "__main__":
    import time
    import threading

    logging.basicConfig(level=logging.INFO)

    display = CabinetDisplayGUI(fullscreen=False)

    # Simulate some messages
    def test_sequence():
        time.sleep(2)
        display.handle_message({
            "type": "STATE_CHANGE",
            "state": "AUTHENTICATING",
            "message": "Reading card..."
        })

        time.sleep(2)
        display.handle_message({
            "type": "AUTH_SUCCESS",
            "user": {"name": "John Doe", "email": "john@example.com"},
        })

        time.sleep(3)
        display.handle_message({
            "type": "SESSION_SUMMARY",
            "summary": {
                "borrowed": [
                    {"name": "Arduino Uno"},
                    {"name": "Multimeter"}
                ],
                "returned": [
                    {"name": "Soldering Iron"}
                ]
            },
            "user_name": "John Doe"
        })

        time.sleep(4)
        display.handle_message({
            "type": "STATE_CHANGE",
            "state": "LOCKED",
            "message": "Tap card to unlock"
        })

    threading.Thread(target=test_sequence, daemon=True).start()
    display.run()
