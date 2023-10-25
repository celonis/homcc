# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Test module for the server cache."""

from pathlib import Path
from tempfile import TemporaryDirectory

from homcc.server.cache import Cache


class TestCache:
    """Tests the server cache."""

    def test_simple(self):
        with TemporaryDirectory() as tmp_dir:
            root_dir = Path(tmp_dir)
            cache = Cache(root_dir, 1000)
            cache_dir = root_dir / "cache"

            file1 = bytearray([0x1, 0x2, 0x3, 0x9])
            cache.put("hash1", file1)

            assert cache.get("hash1") == str(cache_dir / "hash1")
            assert "hash1" in cache
            assert Path.read_bytes(Path(cache.get("hash1"))) == file1

            file2 = bytearray([0x3, 0x6, 0x3, 0x9])
            cache.put("hash2", file2)

            assert cache.get("hash2") == str(cache_dir / "hash2")
            assert "hash2" in cache
            assert Path.read_bytes(Path(cache.get("hash2"))) == file2

            file3 = bytearray([0x4, 0x2])
            cache.put("hash3", file3)

            assert cache.get("hash3") == str(cache_dir / "hash3")
            assert "hash3" in cache
            assert Path.read_bytes(Path(cache.get("hash3"))) == file3

            assert "other_hash" not in cache

    @staticmethod
    def assert_hash_in_cache(cache: Cache, hash_value: str):
        assert hash_value in cache
        assert (cache.cache_folder / hash_value).exists()

    @staticmethod
    def assert_hash_not_in_cache(cache: Cache, hash_value: str):
        assert hash_value not in cache
        assert not (cache.cache_folder / hash_value).exists()

    def test_eviction_size_limit(self):
        with TemporaryDirectory() as tmp_dir:
            cache = Cache(Path(tmp_dir), max_size_bytes=10)

            cache.put("hash1", bytearray([0x1, 0x2, 0x3, 0x9]))
            cache.put("hash2", bytearray([0x1, 0x2, 0x3, 0xA]))
            cache.put("hash3", bytearray([0xFF, 0xFF]))
            assert len(cache) == 3
            self.assert_hash_in_cache(cache, "hash1")
            self.assert_hash_in_cache(cache, "hash2")
            self.assert_hash_in_cache(cache, "hash3")

            cache.put("hash4", bytearray([0x1]))
            assert len(cache) == 3
            self.assert_hash_not_in_cache(cache, "hash1")
            self.assert_hash_in_cache(cache, "hash2")
            self.assert_hash_in_cache(cache, "hash3")
            self.assert_hash_in_cache(cache, "hash4")

            cache.put("hash5", bytearray([0x1]))
            assert len(cache) == 4
            self.assert_hash_in_cache(cache, "hash2")
            self.assert_hash_in_cache(cache, "hash3")
            self.assert_hash_in_cache(cache, "hash4")
            self.assert_hash_in_cache(cache, "hash5")

            cache.put("hash6", bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9]))
            assert len(cache) == 2
            self.assert_hash_not_in_cache(cache, "hash2")
            self.assert_hash_not_in_cache(cache, "hash3")
            self.assert_hash_not_in_cache(cache, "hash4")
            self.assert_hash_in_cache(cache, "hash5")
            self.assert_hash_in_cache(cache, "hash6")

    def test_eviction_order_lru(self):
        with TemporaryDirectory() as tmp_dir:
            cache = Cache(Path(tmp_dir), max_size_bytes=10)

            cache.put("hash1", bytearray([0x1, 0x2, 0x3, 0x9]))
            cache.put("hash2", bytearray([0x1, 0x2, 0x3, 0xA]))
            cache.put("hash3", bytearray([0xFF, 0xFF]))
            assert len(cache) == 3
            self.assert_hash_in_cache(cache, "hash1")
            self.assert_hash_in_cache(cache, "hash2")
            self.assert_hash_in_cache(cache, "hash3")

            cache.get("hash1")  # make "hash1" the latest used element
            cache.put("hash4", bytearray([0xFF, 0xFF, 0x0, 0x0]))
            assert len(cache) == 3
            self.assert_hash_not_in_cache(cache, "hash2")
            self.assert_hash_in_cache(cache, "hash1")
            self.assert_hash_in_cache(cache, "hash3")
            self.assert_hash_in_cache(cache, "hash4")

            assert "hash3" in cache  # make "hash3" the latest used element
            cache.put("hash5", bytearray([0xFF, 0xFF, 0x0, 0x0, 0xFF, 0xFF, 0x0, 0x0]))
            assert len(cache) == 2
            self.assert_hash_in_cache(cache, "hash3")
            self.assert_hash_in_cache(cache, "hash5")
            self.assert_hash_not_in_cache(cache, "hash1")
            self.assert_hash_not_in_cache(cache, "hash2")
            self.assert_hash_not_in_cache(cache, "hash4")
