""" Tests for common/compression.py"""
import pytest

from inspect import getmembers, isfunction
from typing import Callable, List, Tuple

from homcc.common.compression import Compression, lzo, lzma

from homcc.common import compression


class TestCompression:
    """
    Tests for parsing related to compression
    """

    # Tuple (name, function) of all functions in homcc.common.compression
    compression_functions: List[Tuple[str, Callable[[bytes, bool], bytes]]] = getmembers(compression, isfunction)

    def test_if_all_compression_functions_are_in_compression_enum(self):
        for name, function in self.compression_functions:
            assert Compression.get(name).value.name == function.__name__

    def test_lzo(self):
        data: bytes = bytes()

        with pytest.raises(NotImplementedError):
            compressed_data: bytes = lzo(data, True)
            assert lzo(compressed_data, False) == data

    def test_lzma(self):
        data: bytes = bytes()

        with pytest.raises(NotImplementedError):
            compressed_data: bytes = lzma(data, True)
            assert lzma(compressed_data, False) == data
