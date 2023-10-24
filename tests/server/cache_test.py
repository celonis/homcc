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

    def test_eviction_size_limit(self):
        with TemporaryDirectory() as tmp_dir:
            root_dir = Path(tmp_dir)
            cache = Cache(root_dir, max_size_bytes=10)
            cache_dir = root_dir / "cache"

            cache.put("hash1", bytearray([0x1, 0x2, 0x3, 0x9]))
            cache.put("hash2", bytearray([0x1, 0x2, 0x3, 0xA]))
            cache.put("hash3", bytearray([0xFF, 0xFF]))
            assert len(cache) == 3
            assert (cache_dir / "hash1").exists()
            assert (cache_dir / "hash2").exists()
            assert (cache_dir / "hash3").exists()

            cache.put("hash4", bytearray([0x1]))
            assert len(cache) == 3
            assert "hash2" in cache
            assert "hash3" in cache
            assert "hash4" in cache
            assert not (cache_dir / "hash1").exists()
            assert (cache_dir / "hash2").exists()
            assert (cache_dir / "hash3").exists()
            assert (cache_dir / "hash4").exists()

            cache.put("hash5", bytearray([0x1]))
            assert len(cache) == 4
            assert "hash2" in cache
            assert "hash3" in cache
            assert "hash4" in cache
            assert "hash5" in cache
            assert (cache_dir / "hash2").exists()
            assert (cache_dir / "hash3").exists()
            assert (cache_dir / "hash4").exists()
            assert (cache_dir / "hash5").exists()

            cache.put("hash6", bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9]))
            assert len(cache) == 2
            assert not (cache_dir / "hash2").exists()
            assert not (cache_dir / "hash3").exists()
            assert not (cache_dir / "hash4").exists()
            assert "hash5" in cache
            assert "hash6" in cache

    def test_eviction_order_lru(self):
        with TemporaryDirectory() as tmp_dir:
            root_dir = Path(tmp_dir)
            cache = Cache(root_dir, max_size_bytes=10)
            cache_dir = root_dir / "cache"

            cache.put("hash1", bytearray([0x1, 0x2, 0x3, 0x9]))
            cache.put("hash2", bytearray([0x1, 0x2, 0x3, 0xA]))
            cache.put("hash3", bytearray([0xFF, 0xFF]))
            assert len(cache) == 3
            assert (cache_dir / "hash1").exists()
            assert (cache_dir / "hash2").exists()
            assert (cache_dir / "hash3").exists()

            cache.get("hash1")  # make "hash1" the latest used element
            cache.put("hash4", bytearray([0xFF, 0xFF, 0x0, 0x0]))
            assert len(cache) == 3
            assert "hash2" not in cache
            assert "hash1" in cache
            assert "hash3" in cache
            assert "hash4" in cache
            # TODO: method for asserts combining IO exists and cache exists to reduce boilerplate
            assert not (cache_dir / "hash2").exists()
            assert (cache_dir / "hash1").exists()
            assert (cache_dir / "hash3").exists()
            assert (cache_dir / "hash4").exists()

            assert "hash3" in cache  # make "hash3" the latest used element
            cache.put("hash5", bytearray([0xFF, 0xFF, 0x0, 0x0, 0xFF, 0xFF, 0x0, 0x0]))
            assert len(cache) == 2
            assert "hash3" in cache
            assert "hash5" in cache
            assert not (cache_dir / "hash1").exists()
            assert not (cache_dir / "hash2").exists()
            assert (cache_dir / "hash3").exists()
            assert not (cache_dir / "hash4").exists()
            assert (cache_dir / "hash5").exists()
