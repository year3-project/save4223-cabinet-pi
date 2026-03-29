"""Configuration management."""

import json
import os
from pathlib import Path

# Default configuration
DEFAULT_CONFIG = {
    # Server settings
    'server_url': 'http://save4223.isd-hub.com',
    'edge_secret': 'edge_device_secret_key',
    'cabinet_id': 1,

    # Database
    'db_path': '/home/pi/save4223/save4223-cabinet-pi/data/local.db',

    # Hardware settings
    'servo_i2c_address': 0x40,
    'nfc_spi_device': 0,
    'rfid_spi_devices': [0, 1, 2],
    'drawer_switch_pins': [17, 27, 22, 23],
    'led_pin': 18,
    'num_drawers': 4,

    # Timing settings
    'session_timeout': 300,  # seconds (5 minutes)
    'rfid_scan_count': 1,  # Number of times to call read_rfid_tags (each call does 5 cycles internally)
    'sync_interval': 60,    # seconds
    'api_timeout': 5,       # seconds
    'api_retry_count': 3,

    # RFID scan tuning (voting mode)
    'rfid': {
        'voting_cycles': 10,
        'min_appearances': 3,
        'read_interval': 1.0,
        'idle_break_timeout': 0.2,
        'max_cycle_wait': 2.0,
    },

    # Cache settings
    'auth_cache_ttl': 3600,  # 1 hour
    'max_pending_sync': 1000,

    # SSL/TLS settings
    'ssl': {
        'verify': True,
        'cert_path': None,
    },

    # API settings
    'api': {
        'timeout': 10,
        'max_retries': 3,
        'retry_delay': 2.0,
    },

    # Display settings
    'display': {
        'enabled': True,
        'fullscreen': True,
        'width': 800,
        'height': 480,
        'host': '0.0.0.0',
        'port': 8080,
    },

    # Hardware mode: 'mock' for testing, 'raspberry_pi' for production
    'hardware': {
        'mode': 'mock',
    },
}


def load_config() -> dict:
    """Load configuration from file or environment."""
    config = DEFAULT_CONFIG.copy()
    
    # Try to load from config file
    config_paths = [
        Path(__file__).parent.parent / 'config.json',
        Path('/etc/cabinet/config.json'),
        Path.home() / '.cabinet' / 'config.json',
    ]
    
    for path in config_paths:
        if path.exists():
            with open(path) as f:
                config.update(json.load(f))
            break
    
    # Override with environment variables
    env_mappings = {
        'CABINET_SERVER_URL': 'server_url',
        'CABINET_EDGE_SECRET': 'edge_secret',
        'CABINET_ID': 'cabinet_id',
        'CABINET_DB_PATH': 'db_path',
    }
    
    for env_var, config_key in env_mappings.items():
        if env_var in os.environ:
            # Convert type if needed
            if config_key in ['cabinet_id']:
                config[config_key] = int(os.environ[env_var])
            else:
                config[config_key] = os.environ[env_var]
    
    return config


# Global config instance
CONFIG = load_config()
