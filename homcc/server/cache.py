"""Caching module of the homcc server."""
import logging
from pathlib import Path
from threading import Lock
from typing import Dict

logger = logging.getLogger(__name__)


class Cache:
    """Represents the homcc server cache that is used to cache dependencies."""

    cache: Dict[str, str]
    """'Hash' -> 'File path' on server map for holding paths to cached files"""
    cache_mutex: Lock
    """Mutex for locking the cache."""
    cache_folder: Path
    """Path to the cache on the file system."""

    def __init__(self, root_folder: Path):
        self.cache_folder = self._create_cache_folder(root_folder)
        self.cache: Dict[str, str] = {}
        self.cache_mutex: Lock = Lock()

    def __contains__(self, key):
        with self.cache_mutex:
            return key in self.cache

    @staticmethod
    def _create_cache_folder(root_temp_folder: Path) -> Path:
        """Creates the cache folder inside the root folder."""
        cache_folder = root_temp_folder / Path("cache")
        cache_folder.mkdir(parents=True, exist_ok=True)

        logger.info("Created cache folder in '%s'.", cache_folder.absolute())
        return cache_folder

    def get(self, hash_value: str) -> str:
        """Gets an entry (path) from the cache given a hash."""
        with self.cache_mutex:
            return self.cache[hash_value]

    def put(self, hash_value: str, content: bytearray):
        """Stores a dependency in the cache."""
        cached_file_path = self.cache_folder / hash_value
        Path.write_bytes(cached_file_path, content)

        with self.cache_mutex:
            self.cache[hash_value] = str(cached_file_path)
