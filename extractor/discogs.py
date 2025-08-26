"""Compatibility import for discogs module."""

import sys
from pathlib import Path


# Add the pyextractor directory to the path
python_extractor_path = Path(__file__).parent / "pyextractor"
sys.path.insert(0, str(python_extractor_path))

# Import all public symbols from the actual discogs module
from discogs import *  # noqa: E402, F403
