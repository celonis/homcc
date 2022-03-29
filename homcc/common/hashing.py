"""shared common functionality regarding hashes"""
import hashlib
import base64

from pathlib import Path


def hash_file_with_bytes(path: str, content: bytes):
    """Same as hash_file_with_path, but allows to supply the file content as parameter."""
    # always use the absolute path for calculating the hash
    absolute_path = Path(path).absolute

    salt = base64.b64encode(str(absolute_path).encode())
    return hashlib.sha1(salt + content).hexdigest()


def hash_file_with_path(path: str) -> str:
    """Generates a hash from the file at the given path. Uses a salt so that
    identical files at different locations yield a different hash."""
    return hash_file_with_bytes(path, Path(path).read_bytes())
