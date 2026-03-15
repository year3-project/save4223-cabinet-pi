#!/usr/bin/env python3
"""Test runner for Smart Cabinet Pi.

Runs all test suites and provides summary report.
"""

import sys
import os
import unittest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent / 'display'))

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'


def print_header(text):
    """Print formatted header."""
    print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}{BLUE} {text}{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}\n")


def print_summary(results):
    """Print test summary."""
    print_header("TEST SUMMARY")

    total = results['total']
    passed = results['passed']
    failed = results['failed']
    errors = results['errors']

    print(f"Total tests: {total}")
    print(f"{GREEN}Passed: {passed}{RESET}")
    print(f"{RED}Failed: {failed}{RESET}")
    print(f"{YELLOW}Errors: {errors}{RESET}")

    if total > 0:
        success_rate = (passed / total) * 100
        print(f"\nSuccess rate: {success_rate:.1f}%")

    return failed == 0 and errors == 0


def run_test_suite(test_module, name):
    """Run a test suite and return results."""
    print(f"\n{BOLD}Running {name}...{RESET}")
    print("-" * 60)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(test_module)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return {
        'total': result.testsRun,
        'passed': result.testsRun - len(result.failures) - len(result.errors),
        'failed': len(result.failures),
        'errors': len(result.errors)
    }


def check_dependencies():
    """Check if all dependencies are available."""
    print_header("DEPENDENCY CHECK")

    deps = {
        'requests': 'HTTP client library',
        'nicegui': 'Display UI (optional)',
    }

    missing = []
    optional_missing = []

    for module, description in deps.items():
        try:
            __import__(module)
            print(f"{GREEN}✓{RESET} {module}: {description}")
        except ImportError:
            if module == 'nicegui':
                optional_missing.append(module)
                print(f"{YELLOW}○{RESET} {module}: {description} (optional)")
            else:
                missing.append(module)
                print(f"{RED}✗{RESET} {module}: {description} (REQUIRED)")

    if missing:
        print(f"\n{RED}Missing required dependencies: {', '.join(missing)}{RESET}")
        print("Install with: pip install " + " ".join(missing))
        return False

    if optional_missing:
        print(f"\n{YELLOW}Optional dependencies missing: {', '.join(optional_missing)}{RESET}")

    return True


def check_config():
    """Check if config file exists and is valid."""
    print_header("CONFIGURATION CHECK")

    config_paths = [
        Path(__file__).parent / 'config.json',
        Path('/etc/cabinet/config.json'),
        Path.home() / '.cabinet' / 'config.json',
    ]

    config_found = False
    for path in config_paths:
        if path.exists():
            print(f"{GREEN}✓{RESET} Config found: {path}")
            config_found = True

            # Try to load it
            try:
                import json
                with open(path) as f:
                    config = json.load(f)

                required = ['server_url', 'edge_secret', 'cabinet_id', 'db_path']
                missing = [k for k in required if k not in config]

                if missing:
                    print(f"{YELLOW}⚠ Missing keys: {', '.join(missing)}{RESET}")
                else:
                    print(f"{GREEN}✓{RESET} Config is valid")

                # Check hardware mode
                mode = config.get('hardware', {}).get('mode', 'mock')
                print(f"  Hardware mode: {BOLD}{mode}{RESET}")

                # Check display settings
                display = config.get('display', {})
                if display.get('enabled', True):
                    print(f"  Display: {GREEN}enabled{RESET}")
                else:
                    print(f"  Display: {YELLOW}disabled{RESET}")

            except Exception as e:
                print(f"{RED}✗ Error loading config: {e}{RESET}")

            break

    if not config_found:
        print(f"{YELLOW}⚠ No config file found{RESET}")
        print("Copy config.cloud.example.json to config.json and edit it")

    return config_found


def main():
    """Main test runner."""
    print_header("SMART CABINET PI - TEST SUITE")

    # Check dependencies
    if not check_dependencies():
        return 1

    # Check config
    check_config()

    # Run tests
    print_header("RUNNING TESTS")

    all_results = {
        'total': 0,
        'passed': 0,
        'failed': 0,
        'errors': 0
    }

    # Import test modules
    test_modules = [
        ('tests.test_state_machine', 'State Machine Tests'),
        ('tests.test_local_db', 'Local Database Tests'),
        ('tests.test_integration', 'Integration Tests'),
    ]

    for module_name, display_name in test_modules:
        try:
            module = __import__(module_name, fromlist=[''])
            results = run_test_suite(module, display_name)

            all_results['total'] += results['total']
            all_results['passed'] += results['passed']
            all_results['failed'] += results['failed']
            all_results['errors'] += results['errors']

        except Exception as e:
            print(f"{RED}Error loading {display_name}: {e}{RESET}")

    # Print final summary
    success = print_summary(all_results)

    if success:
        print(f"\n{GREEN}{BOLD}All tests passed! ✓{RESET}")
        return 0
    else:
        print(f"\n{RED}{BOLD}Some tests failed ✗{RESET}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
