"""Tests the hashing module of homcc."""
from homcc.common.hashing import hash_file_with_bytes


class TestHashing:
    """Tests for common/hashing.py"""

    def test_hash_file_with_bytes_avoid_collision(self):
        file_bytes = bytearray([0x1, 0xA, 0xC])
        hash_some_path = hash_file_with_bytes("some_path", file_bytes)

        hash_other_path = hash_file_with_bytes("other_path", file_bytes)

        assert hash_some_path != hash_other_path
