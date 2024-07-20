class ScrapeMasterError(Exception):
    """Base class for exceptions in ScrapeMaster."""
    pass

class PageFetchError(ScrapeMasterError):
    """Exception raised for errors in fetching a page."""
    pass
