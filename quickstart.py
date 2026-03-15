#!/usr/bin/env python3
"""Quick start script for Smart Cabinet Pi.

Validates setup and runs the cabinet controller.
"""

import sys
import os
from pathlib import Path

# Color codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'


def print_banner():
    """Print welcome banner."""
    print(f"""
{BOLD}{BLUE}
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║           🔐 Smart Cabinet Pi - Quick Start 🔐               ║
║                                                              ║
║     Edge controller for Save4223 smart tool system           ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
{RESET}
""")


def check_python_version():
    """Check Python version."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print(f"{RED}✗ Python 3.10+ required (found {version.major}.{version.minor}){RESET}")
        return False
    print(f"{GREEN}✓{RESET} Python {version.major}.{version.minor}.{version.micro}")
    return True


def check_dependencies():
    """Check required dependencies."""
    print("\nChecking dependencies...")

    required = ['requests']
    optional = ['nicegui']

    all_ok = True

    for pkg in required:
        try:
            __import__(pkg)
            print(f"  {GREEN}✓{RESET} {pkg}")
        except ImportError:
            print(f"  {RED}✗{RESET} {pkg} (required)")
            all_ok = False

    for pkg in optional:
        try:
            __import__(pkg)
            print(f"  {GREEN}✓{RESET} {pkg} (optional)")
        except ImportError:
            print(f"  {YELLOW}○{RESET} {pkg} (optional - install for display)")

    return all_ok


def check_config():
    """Check configuration."""
    print("\nChecking configuration...")

    config_paths = [
        Path('config.json'),
        Path('/etc/cabinet/config.json'),
        Path.home() / '.cabinet' / 'config.json',
    ]

    for path in config_paths:
        if path.exists():
            print(f"  {GREEN}✓{RESET} Config: {path}")
            try:
                import json
                with open(path) as f:
                    config = json.load(f)

                # Show key settings
                mode = config.get('hardware', {}).get('mode', 'mock')
                print(f"    Hardware mode: {BOLD}{mode}{RESET}")

                server = config.get('server_url', 'NOT SET')
                print(f"    Server: {server}")

                display = config.get('display', {}).get('enabled', True)
                print(f"    Display: {'enabled' if display else 'disabled'}")

                return config
            except Exception as e:
                print(f"    {RED}Error reading config: {e}{RESET}")
                return None

    print(f"  {RED}✗{RESET} No config file found!")
    print(f"\n  Run: cp config.cloud.example.json config.json")
    print(f"  Then edit config.json with your settings")
    return None


def check_database():
    """Check database setup."""
    print("\nChecking database...")

    sys.path.insert(0, str(Path(__file__).parent / 'src'))

    try:
        from config import CONFIG
        db_path = Path(CONFIG['db_path'])

        # Create data directory if needed
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Test database
        from local_db import LocalDB
        db = LocalDB(str(db_path))
        stats = db.get_stats()
        db.close()

        print(f"  {GREEN}✓{RESET} Database: {db_path}")
        print(f"    Pending syncs: {stats['pending_syncs']}")
        print(f"    Items in cabinet: {stats['items_in_cabinet']}")
        print(f"    Cached users: {stats['cached_users']}")

        return True
    except Exception as e:
        print(f"  {RED}✗{RESET} Database error: {e}")
        return False


def run_tests():
    """Run test suite."""
    print("\nRun tests? (y/n): ", end='')
    response = input().strip().lower()

    if response == 'y':
        print(f"\n{BLUE}Running tests...{RESET}\n")
        import subprocess
        result = subprocess.run([sys.executable, 'run_tests.py'])
        return result.returncode == 0
    return True


def run_cabinet():
    """Run the cabinet controller."""
    print(f"\n{BOLD}Start Smart Cabinet? (y/n): {RESET}", end='')
    response = input().strip().lower()

    if response == 'y':
        print(f"\n{GREEN}Starting Smart Cabinet...{RESET}\n")
        print("Press Ctrl+C to stop\n")

        sys.path.insert(0, str(Path(__file__).parent / 'src'))
        sys.path.insert(0, str(Path(__file__).parent / 'display'))

        from main import SmartCabinet

        try:
            cabinet = SmartCabinet()
            cabinet.run()
        except KeyboardInterrupt:
            print("\n\nStopped by user")
        except Exception as e:
            print(f"\n{RED}Error: {e}{RESET}")
            import traceback
            traceback.print_exc()


def main():
    """Main quickstart flow."""
    print_banner()

    # Check Python version
    if not check_python_version():
        return 1

    # Check dependencies
    if not check_dependencies():
        print(f"\n{RED}Install missing dependencies: pip install -r requirements.txt{RESET}")
        return 1

    # Check config
    config = check_config()
    if not config:
        return 1

    # Check database
    if not check_database():
        return 1

    print(f"\n{GREEN}{BOLD}✓ Setup looks good!{RESET}")

    # Offer to run tests
    run_tests()

    # Run cabinet
    run_cabinet()

    return 0


if __name__ == '__main__':
    sys.exit(main())
