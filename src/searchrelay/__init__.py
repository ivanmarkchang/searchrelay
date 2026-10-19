"""SearchRelay's shared library interface."""
from .models import SearchRequest, SearchResponse
from .router import Router

__all__ = ["Router", "SearchRequest", "SearchResponse"]
__version__ = "0.1.0"
