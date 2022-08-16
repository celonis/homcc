""" Tests for common/compression.py"""
from homcc.common.compression import LZMA, LZO, CompressedBytes, NoCompression

TEST_DATA: bytearray = bytearray([0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x6, 0x6, 0x9])


class TestCompression:
    """
    Tests for parsing related to compression
    """

    def test_lzo(self):
        lzo = LZO()
        compressed_data = lzo.compress(TEST_DATA)
        assert lzo
        assert lzo.decompress(compressed_data) == TEST_DATA

    def test_lzma(self):
        lzma = LZMA()
        compressed_data = lzma.compress(TEST_DATA)
        assert lzma
        assert lzma.decompress(compressed_data) == TEST_DATA

    def test_no_compression(self):
        no_compression = NoCompression()
        compressed_data = no_compression.compress(TEST_DATA)
        assert not no_compression
        assert no_compression.decompress(compressed_data) == TEST_DATA


class TestCompressedBytes:
    """Tests for the CompressedBytes data structure."""

    def test_no_compression(self):
        compressed_bytes = CompressedBytes(TEST_DATA, NoCompression())

        assert compressed_bytes.get_data() == TEST_DATA
        assert compressed_bytes.compression == NoCompression()
        assert compressed_bytes.to_wire() == TEST_DATA
        assert len(compressed_bytes) == len(TEST_DATA)

        assert compressed_bytes.from_wire(TEST_DATA, NoCompression()).get_data() == TEST_DATA

    @staticmethod
    def compression_test(compression):
        compressed_data = compression.compress(TEST_DATA)

        compressed_bytes = CompressedBytes(TEST_DATA, compression)

        assert compressed_bytes.get_data() == TEST_DATA
        assert compressed_bytes.compression == compression
        assert compressed_bytes.to_wire() == compressed_data
        assert len(compressed_bytes) == len(compressed_data)

        assert compressed_bytes.from_wire(compressed_data, compression).get_data() == TEST_DATA

    def test_lzma(self):
        self.compression_test(LZMA())

    def test_lzo(self):
        self.compression_test(LZO())
