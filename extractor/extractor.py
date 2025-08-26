"""Compatibility import for extractor module."""

import sys
from pathlib import Path


# Add the python-extractor directory to the path
python_extractor_path = Path(__file__).parent / "python-extractor"
sys.path.insert(0, str(python_extractor_path))

# Import all public symbols from the actual extractor
from extractor import *  # noqa: E402, F403
