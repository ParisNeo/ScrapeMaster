"""
ScrapeMaster - Versatile Web Scraping Library
"""
from .core import ScrapeMaster
from .exceptions import (
    ScrapeMasterError,
    PageFetchError,
    StrategyError,
    BlockerDetectedError,
    DriverInitializationError,
    ParsingError
)

# Only import GUI if PySide6 is available (lazy loading)
try:
    from .gui import ScrapeMasterApp, main as run_gui
    GUI_AVAILABLE = True
except ImportError:
    ScrapeMasterApp = None
    run_gui = None
    GUI_AVAILABLE = False

__version__ = "0.8.0"
__all__ = [
    "ScrapeMaster",
    "ScrapeMasterError",
    "PageFetchError",
    "StrategyError",
    "BlockerDetectedError",
    "DriverInitializationError",
    "ParsingError",
    "ScrapeMasterApp",
    "run_gui",
    "GUI_AVAILABLE"
]