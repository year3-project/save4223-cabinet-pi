#!/usr/bin/env python3
"""
Display launcher for Raspberry Pi external monitor.

This script launches the display UI in fullscreen mode on the Pi's external display.
It can run in two modes:
1. Standalone browser mode (for testing): python3 launch-display.py
2. Electron mode (for production): npm start

The display UI provides:
- Real-time cabinet status visualization
- User authentication feedback
- Transaction summaries (borrow/return)
- LED status indicators
- Offline/online sync status
"""

import subprocess
import sys
import os
import argparse
import json
import socket
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# Configuration
DISPLAY_PORT = 9222  # Chrome DevTools Protocol port
HTTP_PORT = 8888     # Local HTTP server port

class DisplayController:
    """Controller for the cabinet display UI."""

    def __init__(self, http_port=HTTP_PORT, fullscreen=True, kiosk=True):
        self.http_port = http_port
        self.fullscreen = fullscreen
        self.kiosk = kiosk
        self.http_server = None
        self.browser_process = None
        self.display_dir = Path(__file__).parent

    def start_http_server(self):
        """Start the HTTP server to serve the display UI."""
        os.chdir(self.display_dir)

        handler = SimpleHTTPRequestHandler
        self.http_server = HTTPServer(('localhost', self.http_port), handler)

        server_thread = threading.Thread(target=self.http_server.serve_forever)
        server_thread.daemon = True
        server_thread.start()

        print(f"HTTP server started on http://localhost:{self.http_port}")
        return self

    def launch_chromium(self):
        """Launch Chromium browser in kiosk mode."""
        url = f"http://localhost:{self.http_port}/index.html"

        cmd = [
            'chromium-browser',
            '--no-sandbox',
            '--disable-gpu',
            '--disable-features=TranslateUI',
            f'--remote-debugging-port={DISPLAY_PORT}',
        ]

        if self.kiosk:
            cmd.append('--kiosk')  # Fullscreen, no UI chrome
        elif self.fullscreen:
            cmd.append('--start-fullscreen')

        cmd.extend([
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-popup-blocking',
            '--autoplay-policy=no-user-gesture-required',
            url
        ])

        print(f"Launching Chromium: {' '.join(cmd)}")
        self.browser_process = subprocess.Popen(cmd)
        return self

    def send_state_update(self, state, user_name=None, user_id=None):
        """Send state update to the display via Chrome DevTools Protocol."""
        # This would use CDP to send messages to the display
        # For now, we'll use a simple file-based approach
        status_file = self.display_dir / '.display_status.json'
        status = {
            'state': state,
            'user_name': user_name,
            'user_id': user_id,
            'timestamp': time.time()
        }
        with open(status_file, 'w') as f:
            json.dump(status, f)
        print(f"Display state updated: {state}")

    def wait(self):
        """Wait for the browser to close."""
        if self.browser_process:
            try:
                self.browser_process.wait()
            except KeyboardInterrupt:
                print("\nShutting down...")
                self.stop()

    def stop(self):
        """Stop the display server and browser."""
        if self.browser_process:
            self.browser_process.terminate()
            self.browser_process.wait()
        if self.http_server:
            self.http_server.shutdown()
        print("Display stopped.")

def main():
    parser = argparse.ArgumentParser(description='Launch Smart Cabinet Display')
    parser.add_argument('--windowed', action='store_true',
                        help='Run in windowed mode (not fullscreen)')
    parser.add_argument('--no-kiosk', action='store_true',
                        help='Run without kiosk mode (shows browser UI)')
    parser.add_argument('--port', type=int, default=HTTP_PORT,
                        help=f'HTTP server port (default: {HTTP_PORT})')
    parser.add_argument('--demo', action='store_true',
                        help='Enable demo mode (cycles through states)')

    args = parser.parse_args()

    print("=" * 50)
    print("Smart Cabinet Display Launcher")
    print("=" * 50)

    # Check if we're on a Raspberry Pi
    is_pi = Path('/proc/device-tree/model').exists() and \
            'raspberry' in Path('/proc/device-tree/model').read_text().lower()

    if is_pi:
        print("Detected Raspberry Pi - launching in kiosk mode")
    else:
        print("Not on Raspberry Pi - launching in windowed mode")

    # Create display controller
    controller = DisplayController(
        http_port=args.port,
        fullscreen=not args.windowed,
        kiosk=not args.no_kiosk and is_pi
    )

    # Start HTTP server
    controller.start_http_server()

    # Launch browser
    try:
        controller.launch_chromium()
    except FileNotFoundError:
        print("Chromium not found, trying google-chrome...")
        try:
            controller.browser_process = subprocess.Popen([
                'google-chrome',
                f'--remote-debugging-port={DISPLAY_PORT}',
                '--kiosk' if not args.no_kiosk else '',
                f'http://localhost:{args.port}/index.html'
            ])
        except FileNotFoundError:
            print("No browser found. Please install Chromium or Chrome.")
            sys.exit(1)

    print("\nDisplay is running. Press Ctrl+C to stop.")
    print(f"Display URL: http://localhost:{args.port}/index.html")

    if args.demo:
        print("Demo mode enabled - display will cycle through states automatically")

    # Wait for browser to close
    controller.wait()

if __name__ == '__main__':
    main()
