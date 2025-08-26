"""Compatibility import for extractor module."""

import importlib.util
from pathlib import Path


# Add the pyextractor directory to the path
python_extractor_path = Path(__file__).parent / "pyextractor"

# Load the actual extractor module directly
spec = importlib.util.spec_from_file_location("pyextractor_module", python_extractor_path / "extractor.py")
if spec is None or spec.loader is None:
    raise ImportError("Could not load pyextractor module")
pyextractor_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pyextractor_module)

# Export main functions
main = pyextractor_module.main
main_async = pyextractor_module.main_async

__all__ = ["main", "main_async"]
