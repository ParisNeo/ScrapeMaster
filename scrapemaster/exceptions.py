"""
Custom Exceptions for ScrapeMaster Library
"""

class ScrapeMasterError(Exception):
    """Base class for exceptions in ScrapeMaster."""
    pass

class PageFetchError(ScrapeMasterError):
    """Exception raised for general errors in fetching a page (e.g., network issues, HTTP errors)."""
    pass

class StrategyError(ScrapeMasterError):
    """Exception raised when a specific scraping strategy fails (e.g., Selenium init error)."""
    pass

class BlockerDetectedError(StrategyError):
    """Exception raised specifically when a JavaScript/Cookie/Captcha blocker page is detected."""
    pass

class DriverInitializationError(StrategyError):
    """Exception raised when a WebDriver (Selenium/UC) fails to initialize."""
    pass

class ParsingError(ScrapeMasterError):
    """Exception raised during HTML parsing or content extraction failures."""
    pass