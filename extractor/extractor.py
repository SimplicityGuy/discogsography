"""Compatibility import for extractor module."""

import sys
from pathlib import Path


# Add the python-extractor directory to the path
python_extractor_path = Path(__file__).parent / "python-extractor"
sys.path.insert(0, str(python_extractor_path))

# Import specific functions from the actual extractor
try:
    # Import the module directly to avoid naming conflicts
    import importlib.util

    spec = importlib.util.spec_from_file_location("python_extractor", python_extractor_path / "extractor.py")
    python_extractor_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(python_extractor_module)

    # Export the main functions
    main = python_extractor_module.main
    main_async = python_extractor_module.main_async

    __all__ = ["main", "main_async"]
except Exception as e:
    # Fallback for import issues
    print(f"Warning: Could not import from extractor: {e}")

    def main() -> None:
        """Placeholder main function."""
        raise ImportError("Extractor main function not available")

    def main_async() -> None:
        """Placeholder async main function."""
        raise ImportError("Extractor main_async function not available")
