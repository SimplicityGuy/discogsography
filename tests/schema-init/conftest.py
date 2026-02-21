"""Conftest for schema-init tests.

Ensures the schema-init/ directory is on sys.path so that neo4j_schema,
postgres_schema, and schema_init can be imported without a package prefix.
This mirrors the runtime environment where Python adds the script's directory
to sys.path[0] automatically.
"""

from pathlib import Path
import sys


# Add schema-init/ to the front of sys.path so the local modules take
# precedence over any identically-named third-party packages.
_SCHEMA_INIT_DIR = str(Path(__file__).parent.parent.parent / "schema-init")
if _SCHEMA_INIT_DIR not in sys.path:
    sys.path.insert(0, _SCHEMA_INIT_DIR)
