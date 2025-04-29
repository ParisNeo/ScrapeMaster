"""
ScrapeMaster Package Initialization
"""
# Version is now managed in pyproject.toml
# __version__ = "0.4.0"

from .core import ScrapeMaster
from .exceptions import ScrapeMasterError, PageFetchError, StrategyError, BlockerDetectedError

__all__ = [
    "ScrapeMaster",
    "ScrapeMasterError",
    "PageFetchError",
    "StrategyError",
    "BlockerDetectedError",
]

print("ScrapeMaster package initialized.")