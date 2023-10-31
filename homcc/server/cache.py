# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Caching module of the homcc server."""
import logging
from collections import OrderedDict
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)


class Cache:
    """Represents the homcc server cache that is used to cache dependencies."""

    cache: OrderedDict[str, str]
    """'Hash' -> 'File path' on server map for holding paths to cached files"""
    cache_mutex: Lock
    """Mutex for locking the cache."""
    cache_folder: Path
    """Path to the cache on the file system."""
    max_size_bytes: int
    """Maximum size of the cache in bytes."""
    current_size_bytes: int
    """Current size of the cache in bytes."""

    def __init__(self, root_folder: Path, max_size_bytes: int):
        if max_size_bytes <= 0:
            raise RuntimeError("Maximum size of cache must be strictly positive.")

        self.cache_folder = self._create_cache_folder(root_folder)
        self.cache: OrderedDict[str, str] = OrderedDict()
        self.cache_mutex: Lock = Lock()
        self.max_size_bytes = max_size_bytes
        self.current_size_bytes = 0

    def _get_cache_file_path(self, hash_value: str) -> Path:
        return self.cache_folder / hash_value

    def __contains__(self, key: str):
        with self.cache_mutex:
            contained: bool = key in self.cache
            if contained:
                self.cache.move_to_end(key)

            return contained

    def __len__(self) -> int:
        with self.cache_mutex:
            return len(self.cache)

    def _evict_oldest(self):
        """
        Evicts the oldest entry from the cache.
        Note: The caller of this method has to ensure that the cache is locked.
        """
        oldest_hash, oldest_path_str = self.cache.popitem(last=False)
        oldest_path = Path(oldest_path_str)

        try:
            self.current_size_bytes -= oldest_path.stat().st_size
            oldest_path.unlink(missing_ok=False)
        except FileNotFoundError:
            logger.error(
                """Tried to evict cache entry with hash '%s', but corresponding cache file at '%s' did not exist. 
                This may lead to an invalid cache size calculation.""",
                oldest_hash,
                oldest_path,
            )

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
            self.cache.move_to_end(hash_value)
            return self.cache[hash_value]

    def put(self, hash_value: str, content: bytearray):
        """Stores a dependency in the cache."""
        if len(content) > self.max_size_bytes:
            logger.error(
                """File with hash '%s' can not be added to cache as it is larger than the maximum cache size.
                (size in bytes: %i, max. cache size in bytes: %i)""",
                hash_value,
                len(content),
                self.max_size_bytes,
            )
            raise RuntimeError("Cache size insufficient")

        cached_file_path = self._get_cache_file_path(hash_value)
        with self.cache_mutex:
            while self.current_size_bytes + len(content) > self.max_size_bytes:
                self._evict_oldest()

            Path.write_bytes(cached_file_path, content)
            self.current_size_bytes += len(content)
            self.cache[hash_value] = str(cached_file_path)
