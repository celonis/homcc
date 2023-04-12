# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Module holding constants, accessible across the project."""

from typing import Tuple

ENCODING: str = "utf-8"
"""General encoding we use."""


TCP_BUFFER_SIZE: int = 65_536
"""Buffer size for TCP"""

DWARF_FILE_SUFFIX = ".dwo"
"""Suffix for fission/dwarf files."""

EXCLUDED_DEPENDENCY_PREFIXES: Tuple = ("/usr/include", "/usr/lib")
"""Dependencies under these paths are excluded from sending (and therefore also path translation on the server)."""
