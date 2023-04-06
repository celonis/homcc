# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Module holding constants, accessible across the project."""

ENCODING: str = "utf-8"
"""General encoding we use."""


TCP_BUFFER_SIZE: int = 65_536
"""Buffer size for TCP"""

DWARF_FILE_SUFFIX = ".dwo"
"""Suffix for fission/dwarf files."""
