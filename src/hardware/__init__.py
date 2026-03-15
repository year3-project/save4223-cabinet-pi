"""Hardware control modules for Smart Cabinet Pi."""

from .base import HardwareInterface, DrawerState, LEDColor
from .mock import MockHardware

try:
    from .raspberry_pi import RaspberryPiHardware
    RPI_AVAILABLE = True
except ImportError:
    RPI_AVAILABLE = False
    RaspberryPiHardware = None

__all__ = [
    'HardwareInterface',
    'DrawerState',
    'LEDColor',
    'MockHardware',
    'RaspberryPiHardware',
    'RPI_AVAILABLE',
]
