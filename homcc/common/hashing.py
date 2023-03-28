# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""shared common functionality regarding hashes"""
import hashlib
from pathlib import Path


def hash_file_with_bytes(content: bytes) -> str:
    """Same as hash_file_with_path, but allows to supply the file content as parameter."""
    return hashlib.sha1(content).hexdigest()


def hash_file_with_path(path: str) -> str:
    """Generates a hash from the file at the given path."""
    return hash_file_with_bytes(Path(path).read_bytes())
