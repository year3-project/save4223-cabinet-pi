"""Configuration management."""

import json
import os
from pathlib import Path

# Default configuration
DEFAULT_CONFIG = {
    # Server settings
    'server_url': 'http://100.83.123.68:3000',
    'edge_secret': 'edge_device_secret_key',
    'cabinet_id': 1,
    
    # Database
    'db_path': '/home/pi/cabinet/data/local.db',
    
    # Hardware settings
    'servo_i2c_address': 0x40,
    'nfc_spi_device': 0,
    'rfid_spi_devices': [0, 1, 2],
    'drawer_switch_pins': [17, 27, 22, 23],
    'led_pin': 18,
    'num_drawers': 4,
    
    # Timing settings
    'session_timeout': 30,  # seconds
    'rfid_scan_count': 10,
    'sync_interval': 60,    # seconds
    'api_timeout': 5,       # seconds
    'api_retry_count': 3,
    
    # Cache settings
    'auth_cache_ttl': 3600,  # 1 hour
    'max_pending_sync': 1000,
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
