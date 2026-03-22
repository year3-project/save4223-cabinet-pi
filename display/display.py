"""NiceGUI-based display for Smart Cabinet Pi.

Pure Python web UI - no npm/Electron needed.
Runs in browser with live WebSocket updates.

New UI Layout:
- Left: Cabinet visualization with 4 drawers and status indicators
- Right: Welcome message + status information
"""

import json
import logging
import queue
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path
from enum import Enum

try:
    from nicegui import ui, app
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    logging.warning("nicegui not installed. Display will be disabled.")

logger = logging.getLogger(__name__)


class DisplayState(Enum):
    """Display states for the cabinet UI."""
    IDLE = "IDLE"
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    CHECKOUT_WARNING = "CHECKOUT_WARNING"
    RFID_SCANNING = "RFID_SCANNING"
    SESSION_SUMMARY = "SESSION_SUMMARY"
    ERROR = "ERROR"


class CabinetDisplayGUI:
    """NiceGUI display for cabinet with new layout."""

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
        self.current_state = DisplayState.IDLE
        self.current_user: Optional[Dict] = None
        self.status_message = "Tap your card to access the cabinet"
        self.drawer_states: Dict[int, bool] = {1: False, 2: False, 3: False, 4: False}
        self.session_summary: Dict[str, List] = {"borrowed": [], "returned": []}

        # UI elements
        self.state_indicator = None
        self.status_title = None
        self.status_label = None
        self.user_card = None
        self.user_name_label = None
        self.summary_container = None
        self.borrowed_list = None
        self.returned_list = None
        self.drawer_indicators: Dict[int, Any] = {}
        self.warning_label = None
        self.scanning_dots = None

        # Track connected clients
        self.clients = set()

        # Thread-safe queue for messages
        self._message_queue = queue.Queue()

    def setup(self):
        """Set up the UI."""
        @ui.page('/')
        def main_page():
            """Main display page with new layout."""
            client_id = ui.context.client.id
            self.clients.add(client_id)

            # Page styling
            ui.add_head_html('''
                <style>
                    body {
                        margin: 0;
                        padding: 0;
                        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                        color: white;
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        overflow: hidden;
                        display: flex;
                    }
                    .cabinet-panel {
                        flex: 1;
                        display: flex;
                        flex-direction: column;
                        align-items: center;
                        justify-content: center;
                        padding: 40px;
                        background: rgba(0, 0, 0, 0.2);
                    }
                    .status-panel {
                        flex: 1.2;
                        display: flex;
                        flex-direction: column;
                        align-items: center;
                        justify-content: center;
                        padding: 60px;
                    }
                    .drawer { position: relative; transition: all 0.3s ease; }
                    .drawer-indicator {
                        position: absolute;
                        top: 8px;
                        right: 8px;
                        width: 12px;
                        height: 12px;
                        border-radius: 50%;
                        transition: all 0.3s ease;
                    }
                    .drawer-indicator.closed { background: transparent; }
                    .drawer-indicator.open {
                        background: #ff4757;
                        box-shadow: 0 0 10px #ff4757, 0 0 20px #ff4757;
                    }
                    @keyframes pulse-warning {
                        0%, 100% { opacity: 1; }
                        50% { opacity: 0.5; }
                    }
                    .scanning-dots { display: flex; gap: 8px; }
                    .scanning-dot {
                        width: 12px;
                        height: 12px;
                        background: #ffd700;
                        border-radius: 50%;
                        animation: scan-pulse 1.4s infinite;
                    }
                    .scanning-dot:nth-child(2) { animation-delay: 0.2s; }
                    .scanning-dot:nth-child(3) { animation-delay: 0.4s; }
                    @keyframes scan-pulse {
                        0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; }
                        40% { transform: scale(1); opacity: 1; }
                    }
                </style>
            ''')

            with ui.element('div').classes('w-full h-screen flex'):
                # Left Panel: Cabinet Visualization
                with ui.element('div').classes('cabinet-panel'):
                    ui.label('Cabinet Status').style('font-size: 24px; color: #8892b0; margin-bottom: 30px; letter-spacing: 2px;')

                    with ui.element('div').style('width: 280px;'):
                        # Cabinet top
                        ui.element('div').style('''
                            width: 100%; height: 30px;
                            background: linear-gradient(180deg, #d4a574 0%, #c4956a 100%);
                            border-radius: 8px 8px 0 0; margin-bottom: 4px;
                        ''')

                        # Cabinet body
                        with ui.element('div').style('display: flex; gap: 4px; background: #2d2d3a; padding: 8px; border-radius: 0 0 8px 8px;'):
                            # Left column: 3 drawers
                            with ui.element('div').style('flex: 1; display: flex; flex-direction: column; gap: 4px;'):
                                for i in range(1, 4):
                                    with ui.element('div').classes(f'drawer').style('''
                                        height: 80px; border-radius: 6px;
                                        background: linear-gradient(135deg, #7ec8e3 0%, #6bb8d3 100%);
                                        display: flex; align-items: center; justify-content: center;
                                    '''):
                                        indicator = ui.element('div').classes('drawer-indicator closed')
                                        self.drawer_indicators[i] = indicator
                                        ui.element('div').style('width: 60%; height: 8px; background: #333; border-radius: 4px;')
                                        ui.label(str(i)).style('position: absolute; bottom: 8px; left: 8px; font-size: 12px; color: rgba(0,0,0,0.3);')

                            # Right column: 1 drawer
                            with ui.element('div').style('flex: 1; display: flex; flex-direction: column; justify-content: flex-end;'):
                                with ui.element('div').classes('drawer').style('''
                                    height: 248px; border-radius: 6px;
                                    background: linear-gradient(135deg, #d4a5d4 0%, #c495c4 100%);
                                    display: flex; align-items: center; justify-content: center;
                                '''):
                                    indicator = ui.element('div').classes('drawer-indicator closed')
                                    self.drawer_indicators[4] = indicator
                                    ui.element('div').style('width: 60%; height: 8px; background: #333; border-radius: 4px;')
                                    ui.label('4').style('position: absolute; bottom: 8px; left: 8px; font-size: 12px; color: rgba(0,0,0,0.3);')

                # Right Panel: Status Display
                with ui.element('div').classes('status-panel'):
                    ui.label('Welcome to Save4223').style('''
                        font-size: 56px; font-weight: 700;
                        background: linear-gradient(135deg, #00d9ff 0%, #00ff88 100%);
                        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                        margin-bottom: 40px; text-align: center;
                    ''')

                    with ui.card().classes('w-full').style('''
                        max-width: 500px; background: rgba(255,255,255,0.05);
                        border: 2px solid rgba(255,255,255,0.1); border-radius: 20px;
                        padding: 40px 60px; text-align: center;
                    ''') as self.status_card:
                        self.status_icon = ui.label('💳').style('font-size: 64px; margin-bottom: 20px;')
                        self.status_label = ui.label('Tap your card to access the cabinet').style('font-size: 24px; color: #e0e0e0;')

                        # Scanning animation (hidden by default)
                        with ui.row().classes('scanning-dots hidden').style('margin-top: 20px;') as self.scanning_container:
                            ui.element('div').classes('scanning-dot')
                            ui.element('div').classes('scanning-dot')
                            ui.element('div').classes('scanning-dot')

                        # Warning details (hidden by default)
                        self.warning_label = ui.label('').style('''
                            margin-top: 15px; padding: 15px;
                            background: rgba(255,71,87,0.1); border-radius: 8px;
                            color: #ff6b6b; display: none;
                        ''')

                    # User info (hidden by default)
                    with ui.card().style('margin-top: 30px; padding: 20px 30px; background: rgba(0,217,255,0.1); border-radius: 12px; border: 1px solid rgba(0,217,255,0.3); display: none;') as self.user_card:
                        self.user_name_label = ui.label('').style('font-size: 28px; font-weight: 600; color: #00d9ff;')

                    # Transaction summary (hidden by default)
                    with ui.column().style('margin-top: 30px; display: none;') as self.summary_container:
                        with ui.column().style('margin-bottom: 20px;') as self.borrowed_section:
                            ui.label('📤 Borrowed').style('font-size: 16px; font-weight: 600; color: #ff6b6b; margin-bottom: 10px;')
                            self.borrowed_list = ui.column()

                        with ui.column() as self.returned_section:
                            ui.label('📥 Returned').style('font-size: 16px; font-weight: 600; color: #51cf66; margin-bottom: 10px;')
                            self.returned_list = ui.column()

            # Auto-refresh timer
            ui.timer(5.0, self._update_ui)

            # Poll message queue
            ui.timer(0.1, self._process_message_queue)

            def on_disconnect():
                self.clients.discard(client_id)
            ui.context.client.on_disconnect(on_disconnect)

    def _update_ui(self):
        """Periodic UI update."""
        pass

    def update_drawer_states(self, states: Dict[int, bool]):
        """Update drawer indicator states.

        Args:
            states: Dict mapping drawer number (1-4) to open state (True=open, False=closed)
        """
        self.drawer_states = states
        for drawer_num, is_open in states.items():
            if drawer_num in self.drawer_indicators:
                indicator = self.drawer_indicators[drawer_num]
                if is_open:
                    indicator.classes('drawer-indicator open', remove='closed')
                else:
                    indicator.classes('drawer-indicator closed', remove='open')

    def any_drawer_open(self) -> bool:
        """Check if any drawer is open."""
        return any(self.drawer_states.values())

    def get_open_drawers(self) -> List[int]:
        """Get list of open drawer numbers."""
        return [num for num, is_open in self.drawer_states.items() if is_open]

    def set_state(self, state: DisplayState, message: str = "", data: Dict = None):
        """Set display state.

        Args:
            state: New DisplayState
            message: Status message
            data: Additional data (user, transactions, etc.)
        """
        self.current_state = state
        data = data or {}

        # Reset visibility
        self.user_card.style('display: none;')
        self.summary_container.style('display: none;')
        self.scanning_container.classes('hidden', remove='')
        self.warning_label.style('display: none;')
        self.status_card.classes(remove='success warning processing')

        if state == DisplayState.IDLE:
            self.status_icon.set_text('💳')
            self.status_label.set_text(message or "Tap your card to access the cabinet")

        elif state == DisplayState.LOGIN_SUCCESS:
            self.status_card.classes('success')
            self.status_icon.set_text('✅')
            self.status_label.set_text(message or "Login successful, you may now open the cabinet")
            if data.get('user'):
                self.current_user = data['user']
                self.user_name_label.set_text(data['user'].get('name', data['user'].get('user_name', 'User')))
                self.user_card.style('display: block;')

        elif state == DisplayState.CHECKOUT_WARNING:
            self.status_card.classes('warning')
            self.status_icon.set_text('⚠️')
            self.status_label.set_text(message or "Please close all drawers to complete checkout")
            open_drawers = self.get_open_drawers()
            if open_drawers:
                self.warning_label.set_text(f"Open drawers: {', '.join(map(str, open_drawers))}")
                self.warning_label.style('display: block;')

        elif state == DisplayState.RFID_SCANNING:
            self.status_card.classes('processing')
            self.status_icon.set_text('📡')
            self.status_label.set_text(message or "RFID Scanning in progress")
            self.scanning_container.classes(remove='hidden')

        elif state == DisplayState.SESSION_SUMMARY:
            self.status_card.classes('success')
            self.status_icon.set_text('✓')
            self.status_label.set_text(message or "Session complete!")

            if data.get('user'):
                self.user_name_label.set_text(data['user'].get('name', 'User'))
                self.user_card.style('display: block;')

            borrowed = data.get('borrowed', [])
            returned = data.get('returned', [])

            if borrowed or returned:
                self._update_transaction_lists(borrowed, returned)
                self.summary_container.style('display: flex;')

        elif state == DisplayState.ERROR:
            self.status_card.classes('warning')
            self.status_icon.set_text('❌')
            self.status_label.set_text(message or "An error occurred")

    def _update_transaction_lists(self, borrowed: List[Dict], returned: List[Dict]):
        """Update transaction summary lists."""
        # Update borrowed list
        self.borrowed_list.clear()
        with self.borrowed_list:
            if borrowed:
                self.borrowed_section.style('display: block;')
                for item in borrowed:
                    with ui.row().style('padding: 10px 15px; background: rgba(255,255,255,0.05); border-radius: 8px; margin-bottom: 8px;'):
                        ui.label('📤').style('font-size: 20px;')
                        ui.label(item.get('name', item.get('rfid', 'Unknown'))).style('font-size: 16px;')
            else:
                self.borrowed_section.style('display: none;')

        # Update returned list
        self.returned_list.clear()
        with self.returned_list:
            if returned:
                self.returned_section.style('display: block;')
                for item in returned:
                    with ui.row().style('padding: 10px 15px; background: rgba(255,255,255,0.05); border-radius: 8px; margin-bottom: 8px;'):
                        ui.label('📥').style('font-size: 20px;')
                        ui.label(item.get('name', item.get('rfid', 'Unknown'))).style('font-size: 16px;')
            else:
                self.returned_section.style('display: none;')

    def handle_message(self, message: Dict[str, Any]):
        """Handle message from main app."""
        msg_type = message.get("type", "")

        if msg_type == "STATE_CHANGE":
            state_str = message.get("state", "IDLE")
            try:
                state = DisplayState[state_str]
            except KeyError:
                state = DisplayState.IDLE
            self.set_state(state, message.get("message", ""))

        elif msg_type == "DRAWER_STATES":
            self.update_drawer_states(message.get("states", {}))

        elif msg_type == "AUTH_SUCCESS":
            self.current_user = message.get("user", {})
            self.set_state(DisplayState.LOGIN_SUCCESS, data={"user": self.current_user})

        elif msg_type == "AUTH_FAILURE":
            self.set_state(DisplayState.ERROR, message.get("error", "Access denied"))

        elif msg_type == "CHECKOUT_ATTEMPT":
            # Check if drawers are closed
            if self.any_drawer_open():
                self.set_state(DisplayState.CHECKOUT_WARNING)
            else:
                self.set_state(DisplayState.RFID_SCANNING)

        elif msg_type == "SESSION_SUMMARY":
            self.session_summary = {
                "borrowed": message.get("borrowed", []),
                "returned": message.get("returned", [])
            }
            self.set_state(
                DisplayState.SESSION_SUMMARY,
                user_name=message.get("user_name"),
                data={
                    "user": {"name": message.get("user_name", "User")},
                    "borrowed": self.session_summary["borrowed"],
                    "returned": self.session_summary["returned"]
                }
            )

        elif msg_type == "WARNING":
            self.set_state(DisplayState.ERROR, message.get("message", ""))

    def _process_message_queue(self):
        """Drain message queue."""
        try:
            while True:
                message = self._message_queue.get_nowait()
                self.handle_message(message)
        except queue.Empty:
            pass

    def run(self):
        """Run the display (blocking)."""
        self.setup()

        if self.fullscreen:
            import subprocess
            import time
            import threading

            def open_kiosk():
                time.sleep(2)
                try:
                    subprocess.Popen([
                        'chromium-browser',
                        f'http://localhost:{self.port}',
                        '--kiosk',
                        '--noerrdialogs',
                        '--disable-infobars',
                    ])
                except FileNotFoundError:
                    try:
                        subprocess.Popen([
                            'google-chrome',
                            f'http://localhost:{self.port}',
                            '--kiosk',
                        ])
                    except FileNotFoundError:
                        pass

            threading.Thread(target=open_kiosk, daemon=True).start()

        ui.run(
            host=self.host,
            port=self.port,
            title="Save4223",
            favicon="🔧",
            reload=False,
            show=False
        )

    def _run_server(self):
        """Run NiceGUI server in this thread."""
        import asyncio
        asyncio.set_event_loop(asyncio.new_event_loop())
        self.setup()
        ui.run(
            host=self.host,
            port=self.port,
            title="Save4223",
            favicon="🔧",
            reload=False,
            show=False,
        )


class DisplayThread:
    """Thread wrapper for NiceGUI display."""

    def __init__(self, width: int = 800, height: int = 480, fullscreen: bool = True):
        self.display = CabinetDisplayGUI(
            host="0.0.0.0",
            port=8080,
            fullscreen=fullscreen
        )
        self._thread = None

    def start(self):
        """Start display server in background thread."""
        import threading
        self._thread = threading.Thread(target=self.display._run_server, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the display."""
        pass

    def join(self, timeout: float = None):
        if self._thread:
            self._thread.join(timeout=timeout)

    def send_message(self, message: Dict[str, Any]):
        """Thread-safe: put message on queue."""
        self.display._message_queue.put(message)

    # Convenience methods
    def set_drawer_states(self, states: Dict[int, bool]):
        """Update drawer states."""
        self.send_message({"type": "DRAWER_STATES", "states": states})

    def set_state(self, state: str, message: str = "", **kwargs):
        """Set display state."""
        self.send_message({"type": "STATE_CHANGE", "state": state, "message": message, **kwargs})

    def show_login_success(self, user: Dict):
        """Show login success state."""
        self.send_message({"type": "AUTH_SUCCESS", "user": user})

    def show_checkout_attempt(self):
        """Attempt checkout, will warn if drawers open."""
        self.send_message({"type": "CHECKOUT_ATTEMPT"})

    def show_session_summary(self, borrowed: List, returned: List, user_name: str = ""):
        """Show session summary."""
        self.send_message({
            "type": "SESSION_SUMMARY",
            "borrowed": borrowed,
            "returned": returned,
            "user_name": user_name
        })


if __name__ == "__main__":
    import sys
    import time
    import threading

    logging.basicConfig(level=logging.INFO)

    sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

    display = CabinetDisplayGUI(fullscreen=False)

    def demo_loop():
        """Demo loop showing all states."""
        time.sleep(3)

        # Login success
        display._message_queue.put({
            "type": "AUTH_SUCCESS",
            "user": {"name": "Demo User"}
        })
        time.sleep(3)

        # Open some drawers
        display._message_queue.put({
            "type": "DRAWER_STATES",
            "states": {1: True, 2: False, 3: True, 4: False}
        })
        time.sleep(2)

        # Try checkout with open drawers
        display._message_queue.put({"type": "CHECKOUT_ATTEMPT"})
        time.sleep(3)

        # Close drawers and scan
        display._message_queue.put({
            "type": "DRAWER_STATES",
            "states": {1: False, 2: False, 3: False, 4: False}
        })
        display._message_queue.put({"type": "STATE_CHANGE", "state": "RFID_SCANNING"})
        time.sleep(3)

        # Show summary
        display._message_queue.put({
            "type": "SESSION_SUMMARY",
            "user_name": "Demo User",
            "borrowed": [{"name": "Arduino Uno", "rfid": "RFID-001"}],
            "returned": [{"name": "Multimeter", "rfid": "RFID-003"}]
        })
        time.sleep(5)

        # Back to idle
        display._message_queue.put({
            "type": "STATE_CHANGE",
            "state": "IDLE"
        })

    threading.Thread(target=demo_loop, daemon=True).start()
    display.run()
