"""NiceGUI-based display for Smart Cabinet Pi.

Pure Python web UI - no npm/Electron needed.
Runs in browser with live WebSocket updates.

New UI Layout:
- Left: Cabinet visualization with 4 vertical drawers and status indicators
- Right: Welcome message + status information

Integrates with real hardware for NFC reading and drawer switch state.
"""

import json
import logging
import queue
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path
from enum import Enum
import sys
import threading
import time

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

    def __init__(self, host: str = "0.0.0.0", port: int = 8080, fullscreen: bool = True,
                 hardware=None):
        """Initialize display.

        Args:
            host: Host to bind to
            port: Port to serve on
            fullscreen: Whether to launch in fullscreen/kiosk mode
            hardware: Hardware interface instance for real sensor reading
        """
        if not NICEGUI_AVAILABLE:
            raise ImportError("nicegui is required. Install with: pip install nicegui")

        self.host = host
        self.port = port
        self.fullscreen = fullscreen
        self.hardware = hardware

        # Current state
        self.current_state = DisplayState.IDLE
        self.current_user: Optional[Dict] = None
        self.status_message = "Tap your card to access the cabinet"
        self.drawer_states: Dict[int, bool] = {0: False, 1: False, 2: False, 3: False}
        self.session_summary: Dict[str, List] = {"borrowed": [], "returned": []}

        # UI elements
        self.drawer_indicators: Dict[int, Any] = {}
        self.status_card = None
        self.status_icon = None
        self.status_label = None
        self.user_card = None
        self.user_name_label = None
        self.summary_container = None
        self.borrowed_list = None
        self.returned_list = None
        self.warning_label = None
        self.scanning_container = None

        # Track connected clients
        self.clients = set()

        # Thread-safe queue for messages
        self._message_queue = queue.Queue()

        # Hardware polling
        self._poll_hardware = True

    def setup(self):
        """Set up the UI."""
        @ui.page('/')
        def main_page():
            """Main display page with new layout."""
            client_id = ui.context.client.id
            self.clients.add(client_id)

            # Page styling - DaisyUI ISD Theme
            ui.add_head_html('''
                <style>
                    :root {
                        --color-base-100: oklch(98% 0.003 247.858);
                        --color-base-200: oklch(96% 0.007 247.896);
                        --color-base-300: oklch(92% 0.013 255.508);
                        --color-base-content: oklch(27% 0.041 260.031);
                        --color-primary: #F1F7FF;
                        --color-primary-content: #003974;
                        --color-secondary: #FFF4F2;
                        --color-secondary-content: #EC7B60;
                        --color-accent: #003974;
                        --color-accent-content: #FFFFFF;
                        --color-success: oklch(87% 0.15 154.449);
                        --color-success-content: oklch(27% 0.072 132.109);
                        --color-warning: oklch(83% 0.128 66.29);
                        --color-warning-content: oklch(26% 0.079 36.259);
                        --color-error: oklch(71% 0.194 13.428);
                        --color-error-content: oklch(28% 0.109 3.907);
                        --radius: 0.5rem;
                    }
                    body {
                        margin: 0; padding: 0;
                        background: var(--color-base-100);
                        color: var(--color-base-content);
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        overflow: hidden;
                        display: flex;
                    }
                    .cabinet-panel {
                        flex: 0.8; display: flex; flex-direction: column;
                        align-items: center; justify-content: center; padding: 30px;
                        background: var(--color-base-200);
                        border-right: 1px solid var(--color-base-300);
                    }
                    .status-panel {
                        flex: 1.2; display: flex; flex-direction: column;
                        align-items: center; justify-content: center; padding: 40px;
                        background: var(--color-base-100);
                    }
                    .cabinet-container { position: relative; width: 200px; }
                    .cabinet-top {
                        width: 100%; height: 25px;
                        background: linear-gradient(180deg, #d4a574 0%, #c4956a 100%);
                        border-radius: var(--radius) var(--radius) 0 0;
                    }
                    .cabinet-body {
                        background: var(--color-base-300);
                        padding: 8px; border-radius: 0 0 var(--radius) var(--radius);
                        display: flex; flex-direction: column; gap: 6px;
                    }
                    .drawer {
                        position: relative; height: 60px; border-radius: var(--radius);
                        background: linear-gradient(135deg, #5a9fd4 0%, #4a8fc4 100%);
                        display: flex; align-items: center; justify-content: center;
                        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    }
                    .drawer-handle { width: 50%; height: 6px; background: #333; border-radius: 3px; }
                    .drawer-indicator {
                        position: absolute; top: 6px; right: 8px;
                        width: 12px; height: 12px; border-radius: 50%;
                        background: var(--color-success); border: 2px solid rgba(255,255,255,0.5);
                        transition: all 0.3s ease; opacity: 0;
                    }
                    .drawer-indicator.open {
                        opacity: 1; background: var(--color-error);
                        box-shadow: 0 0 8px var(--color-error);
                        animation: pulse-warning 1s infinite;
                    }
                    .drawer-number {
                        position: absolute; bottom: 4px; left: 6px;
                        font-size: 10px; font-weight: 600; color: rgba(0,0,0,0.3);
                    }
                    @keyframes pulse-warning {
                        0%, 100% { opacity: 1; box-shadow: 0 0 8px var(--color-error); }
                        50% { opacity: 0.7; box-shadow: 0 0 16px var(--color-error); }
                    }
                    .scanning-dots { display: flex; gap: 6px; margin-top: 15px; }
                    .scanning-dot {
                        width: 10px; height: 10px;
                        background: var(--color-warning); border-radius: 50%;
                        animation: scan-pulse 1.4s infinite;
                    }
                    .scanning-dot:nth-child(2) { animation-delay: 0.2s; }
                    .scanning-dot:nth-child(3) { animation-delay: 0.4s; }
                    @keyframes scan-pulse {
                        0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; }
                        40% { transform: scale(1); opacity: 1; }
                    }
                    .hidden { display: none !important; }
                </style>
            ''')

            with ui.element('div').classes('w-full h-screen flex'):
                # Left Panel: Cabinet Visualization (4 vertical drawers)
                with ui.element('div').classes('cabinet-panel'):
                    ui.label('Cabinet Status').style('font-size: 18px; color: #8892b0; margin-bottom: 20px; letter-spacing: 1px; text-transform: uppercase;')

                    with ui.element('div').classes('cabinet-container'):
                        # Cabinet top (wood)
                        ui.element('div').classes('cabinet-top')

                        # Cabinet body with 4 drawers stacked vertically
                        with ui.element('div').classes('cabinet-body'):
                            for i in range(4):
                                with ui.element('div').classes('drawer'):
                                    indicator = ui.element('div').classes('drawer-indicator closed')
                                    self.drawer_indicators[i] = indicator
                                    ui.element('div').classes('drawer-handle')
                                    ui.label(str(i + 1)).classes('drawer-number')

                # Right Panel: Status Display
                with ui.element('div').classes('status-panel'):
                    ui.label('Welcome to Save4223').style('''
                        font-size: 36px; font-weight: 700;
                        color: var(--color-accent);
                        margin-bottom: 30px; text-align: center;
                    ''')

                    with ui.card().classes('w-full').style('''
                        max-width: 450px; background: white;
                        border: 2px solid var(--color-base-300); border-radius: var(--radius);
                        padding: 30px 40px; text-align: center;
                        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    ''') as self.status_card:
                        self.status_icon = ui.label('💳').style('font-size: 48px; margin-bottom: 15px;')
                        self.status_label = ui.label('Tap your card to access the cabinet').style('font-size: 18px; color: var(--color-base-content); line-height: 1.5;')

                        # Scanning animation
                        with ui.row().classes('scanning-dots hidden').style('') as self.scanning_container:
                            ui.element('div').classes('scanning-dot')
                            ui.element('div').classes('scanning-dot')
                            ui.element('div').classes('scanning-dot')

                        # Warning label
                        self.warning_label = ui.label('').style('''
                            margin-top: 12px; padding: 10px;
                            background: var(--color-secondary); border-radius: var(--radius);
                            color: var(--color-secondary-content); font-size: 14px;
                        ''')
                        self.warning_label.classes('hidden')

                    # User info
                    with ui.card().style('margin-top: 20px; padding: 15px 25px; background: var(--color-primary); border-radius: var(--radius); display: none;') as self.user_card:
                        self.user_name_label = ui.label('').style('font-size: 20px; font-weight: 600; color: var(--color-primary-content);')

                    # Transaction summary
                    with ui.column().style('margin-top: 20px; display: none; text-align: left; width: 100%; max-width: 450px;') as self.summary_container:
                        with ui.column().style('margin-bottom: 12px; background: white; border-radius: var(--radius); padding: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 4px solid var(--color-error);') as self.borrowed_section:
                            ui.label('📤 Borrowed').style('font-size: 14px; font-weight: 600; color: var(--color-error-content); margin-bottom: 8px;')
                            self.borrowed_list = ui.column()

                        with ui.column().style('background: white; border-radius: var(--radius); padding: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 4px solid var(--color-success);') as self.returned_section:
                            ui.label('📥 Returned').style('font-size: 14px; font-weight: 600; color: var(--color-success-content); margin-bottom: 8px;')
                            self.returned_list = ui.column()

            # Timer to poll message queue
            ui.timer(0.1, self._process_message_queue)

            # Timer to poll hardware (drawer states)
            if self.hardware:
                ui.timer(0.2, self._poll_drawer_states)

            def on_disconnect():
                self.clients.discard(client_id)
            ui.context.client.on_disconnect(on_disconnect)

    def _poll_drawer_states(self):
        """Poll hardware for drawer states."""
        if not self.hardware or not self._poll_hardware:
            return

        # Check if hardware is initialized
        if not getattr(self.hardware, '_initialized', False):
            return

        try:
            # Import here to avoid issues if hardware module not available
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
            from hardware.base import DrawerState

            new_states = {}
            for i in range(4):
                state = self.hardware.get_drawer_state(i)
                new_states[i] = (state == DrawerState.OPEN)

            if new_states != self.drawer_states:
                self.update_drawer_indicators(new_states)
        except Exception as e:
            logger.debug(f"Error polling drawer states: {e}")

    def update_drawer_indicators(self, states: Dict[int, bool]):
        """Update drawer indicator states.

        Args:
            states: Dict mapping drawer index (0-3) to open state (True=open, False=closed)
        """
        self.drawer_states = states
        for drawer_idx, is_open in states.items():
            if drawer_idx in self.drawer_indicators:
                indicator = self.drawer_indicators[drawer_idx]
                if is_open:
                    indicator.classes('drawer-indicator open', remove='closed')
                else:
                    indicator.classes('drawer-indicator closed', remove='open')

    def any_drawer_open(self) -> bool:
        """Check if any drawer is open."""
        return any(self.drawer_states.values())

    def get_open_drawers(self) -> List[int]:
        """Get list of open drawer indices."""
        return [idx for idx, is_open in self.drawer_states.items() if is_open]

    def set_state(self, state: DisplayState, message: str = "", data: Optional[Dict] = None):
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
        self.warning_label.classes('hidden', remove='')
        self.status_card.classes(remove='success warning processing')

        # Reset card border style (ISD theme default)
        self.status_card.style('''
            max-width: 450px; background: white;
            border: 2px solid var(--color-base-300); border-radius: var(--radius);
            padding: 30px 40px; text-align: center;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        ''')

        if state == DisplayState.IDLE:
            self.status_icon.set_text('💳')
            self.status_label.set_text(message or "Tap your card to access the cabinet")

        elif state == DisplayState.LOGIN_SUCCESS:
            self.status_card.style('''
                max-width: 450px; background: white;
                border: 2px solid var(--color-success); border-radius: var(--radius);
                padding: 30px 40px; text-align: center;
                box-shadow: 0 0 0 4px rgba(134,239,172,0.2);
            ''')
            self.status_icon.set_text('✅')
            self.status_label.set_text(message or "Login successful, you may now open the cabinet")
            if data.get('user'):
                self.current_user = data['user']
                self.user_name_label.set_text(data['user'].get('name', data['user'].get('user_name', 'User')))
                self.user_card.style('display: block;')

        elif state == DisplayState.CHECKOUT_WARNING:
            self.status_card.style('''
                max-width: 450px; background: white;
                border: 2px solid var(--color-error); border-radius: var(--radius);
                padding: 30px 40px; text-align: center;
                box-shadow: 0 0 0 4px rgba(252,165,165,0.2);
            ''')
            self.status_icon.set_text('⚠️')
            self.status_label.set_text(message or "Please close all drawers to complete checkout")
            open_drawers = self.get_open_drawers()
            if open_drawers:
                drawer_nums = [str(d + 1) for d in open_drawers]  # 1-indexed for display
                self.warning_label.set_text(f"Open drawers: {', '.join(drawer_nums)}")
                self.warning_label.classes(remove='hidden')

        elif state == DisplayState.RFID_SCANNING:
            self.status_card.style('''
                max-width: 450px; background: white;
                border: 2px solid var(--color-warning); border-radius: var(--radius);
                padding: 30px 40px; text-align: center;
                box-shadow: 0 0 0 4px rgba(253,224,71,0.2);
            ''')
            self.status_icon.set_text('📡')
            self.status_label.set_text(message or "RFID Scanning in progress")
            self.scanning_container.classes(remove='hidden')

        elif state == DisplayState.SESSION_SUMMARY:
            self.status_card.style('''
                max-width: 450px; background: white;
                border: 2px solid var(--color-success); border-radius: var(--radius);
                padding: 30px 40px; text-align: center;
                box-shadow: 0 0 0 4px rgba(134,239,172,0.2);
            ''')
            self.status_icon.set_text('✓')
            self.status_label.set_text(message or "Session complete!")

            if data.get('user'):
                self.user_name_label.set_text(data['user'].get('name', 'User'))
                self.user_card.style('display: block;')

            borrowed = data.get('borrowed', [])
            returned = data.get('returned', [])

            if borrowed or returned:
                self._update_transaction_lists(borrowed, returned)
                self.summary_container.style('display: block;')

        elif state == DisplayState.ERROR:
            self.status_card.style('''
                max-width: 450px; background: white;
                border: 2px solid var(--color-error); border-radius: var(--radius);
                padding: 30px 40px; text-align: center;
                box-shadow: 0 0 0 4px rgba(252,165,165,0.2);
            ''')
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
                    with ui.row().style('padding: 8px 12px; background: var(--color-base-200); border-radius: var(--radius); margin-bottom: 4px; align-items: center;'):
                        ui.label('📤').style('font-size: 14px;')
                        ui.label(item.get('name', item.get('rfid', 'Unknown'))).style('font-size: 14px; color: var(--color-base-content);')
            else:
                self.borrowed_section.style('display: none;')

        # Update returned list
        self.returned_list.clear()
        with self.returned_list:
            if returned:
                self.returned_section.style('display: block;')
                for item in returned:
                    with ui.row().style('padding: 8px 12px; background: var(--color-base-200); border-radius: var(--radius); margin-bottom: 4px; align-items: center;'):
                        ui.label('📥').style('font-size: 14px;')
                        ui.label(item.get('name', item.get('rfid', 'Unknown'))).style('font-size: 14px; color: var(--color-base-content);')
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
            self.update_drawer_indicators(message.get("states", {}))

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
            borrowed = message.get("borrowed", [])
            returned = message.get("returned", [])
            user_name = message.get("user_name", "User")

            self.session_summary = {"borrowed": borrowed, "returned": returned}
            self.set_state(
                DisplayState.SESSION_SUMMARY,
                data={
                    "user": {"name": user_name},
                    "borrowed": borrowed,
                    "returned": returned
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

    def __init__(self, width: int = 800, height: int = 480, fullscreen: bool = True,
                 hardware=None):
        self.display = CabinetDisplayGUI(
            host="0.0.0.0",
            port=8080,
            fullscreen=fullscreen,
            hardware=hardware
        )
        self._thread = None

    def start(self):
        """Start display server in background thread."""
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


# Standalone test with real hardware
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Try to import real hardware
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
        from hardware import RaspberryPiHardware
        hw = RaspberryPiHardware()
        hw.initialize()
        print("Using RaspberryPiHardware")
    except Exception as e:
        print(f"Hardware not available: {e}")
        hw = None

    display = CabinetDisplayGUI(fullscreen=False, hardware=hw)

    if hw:
        def demo_loop():
            """Demo loop with real hardware."""
            time.sleep(3)

            # Login success
            display._message_queue.put({
                "type": "AUTH_SUCCESS",
                "user": {"name": "Demo User"}
            })
            time.sleep(5)

            # Try checkout (will check real drawer states)
            display._message_queue.put({"type": "CHECKOUT_ATTEMPT"})

            # Wait for user to close drawers or continue
            time.sleep(10)

            # Simulate scanning
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
            display._message_queue.put({"type": "STATE_CHANGE", "state": "IDLE"})

        threading.Thread(target=demo_loop, daemon=True).start()

    display.run()
