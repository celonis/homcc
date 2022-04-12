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
    compression_functions: List[Tuple[str, Callable[[bytes], bytes]]] = getmembers(compression, isfunction)

    def test_all_compression_functions_in_compression_enum(self):
        for name, function in self.compression_functions:
            assert Compression.get(name).value.name == function.__name__

    def test_lzo(self):
        with pytest.raises(NotImplementedError):
            _ = lzo(bytes())

    def test_todo(self):
        with pytest.raises(NotImplementedError):
            _ = lzma(bytes())
