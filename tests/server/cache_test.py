"""Test module for the server cache."""

from pathlib import Path
from tempfile import TemporaryDirectory

from homcc.server.cache import Cache


class TestCache:
    """Tests the server cache."""

    def test(self):
        with TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            cache = Cache(cache_dir)

            file1 = bytearray([0x1, 0x2, 0x3, 0x9])
            cache.put("hash1", file1)

            assert cache.get("hash1") == str(cache_dir / "cache" / "hash1")
            assert "hash1" in cache
            assert Path.read_bytes(Path(cache.get("hash1"))) == file1

            file2 = bytearray([0x3, 0x6, 0x3, 0x9])
            cache.put("hash2", file2)

            assert cache.get("hash2") == str(cache_dir / "cache" / "hash2")
            assert "hash2" in cache
            assert Path.read_bytes(Path(cache.get("hash2"))) == file2

            file3 = bytearray([0x4, 0x2])
            cache.put("hash3", file3)

            assert cache.get("hash3") == str(cache_dir / "cache" / "hash3")
            assert "hash3" in cache
            assert Path.read_bytes(Path(cache.get("hash3"))) == file3

            assert "other_hash" not in cache
