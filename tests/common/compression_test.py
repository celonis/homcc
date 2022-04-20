""" Tests for common/compression.py"""
from cgi import test
from unittest import TextTestResult
from homcc.common.compression import LZO, LZMA, CompressedBytes, NoCompression


test_data = bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x6, 0x6, 0x9])


class TestCompression:
    """
    Tests for parsing related to compression
    """

    def test_lzo(self):
        lzo = LZO()
        compressed_data = lzo.compress(test_data)
        assert lzo.decompress(compressed_data) == test_data

    def test_lzma(self):
        lzma = LZMA()
        compressed_data = lzma.compress(test_data)
        assert lzma.decompress(compressed_data) == test_data

    def test_no_compression(self):
        no_compression = NoCompression()
        compressed_data = no_compression.compress(test_data)
        assert no_compression.decompress(compressed_data) == test_data


class TestCompressedBytes:
    """Tests for the CompressedBytes data structure."""

    def test_no_compression(self):
        compressed_bytes = CompressedBytes(test_data, NoCompression())

        assert compressed_bytes.get_data() == test_data
        assert compressed_bytes.compression == NoCompression()
        assert compressed_bytes.to_wire() == test_data
        assert len(compressed_bytes) == len(test_data)

        assert compressed_bytes.from_wire(test_data, NoCompression()).get_data() == test_data

    def compression_test(self, compression):
        lzo_compressed_data = compression.compress(test_data)

        compressed_bytes = CompressedBytes(test_data, compression)

        assert compressed_bytes.get_data() == test_data
        assert compressed_bytes.compression == compression
        assert compressed_bytes.to_wire() == lzo_compressed_data
        assert len(compressed_bytes) == len(lzo_compressed_data)

        assert compressed_bytes.from_wire(lzo_compressed_data, compression).get_data() == test_data

    def test_lzma(self):
        self.compression_test(LZMA())

    def test_lzo(self):
        self.compression_test(LZO())
