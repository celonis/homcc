"""Compression related functionality"""
from __future__ import annotations

from enum import Enum
from typing import Callable, List, Optional


def lzo(_: bytes) -> bytes:
    """Lempel–Ziv–Oberhumer compression algorithm"""
    raise NotImplementedError


def lzma(_: bytes) -> bytes:
    """Lempel–Ziv–Markov chain algorithm"""
    raise NotImplementedError


class _CompressionFunctionWrapper:
    """
    Wrapper for compression functions to allow callable storage in Enum and access to their name and doc strings
    """

    def __init__(self, function: Callable[[bytes], bytes]):
        self.function = function
        self.doc: Optional[str] = function.__doc__
        self.name: str = function.__name__

    def __call__(self, data: bytes) -> bytes:
        return self.function(data)


class Compression(Enum):
    """Enum class of all supported compression types"""

    LZO = _CompressionFunctionWrapper(lzo)
    LZMA = _CompressionFunctionWrapper(lzma)

    def __call__(self, data: bytes) -> bytes:
        return self.value(data)

    @staticmethod
    def get(item: str) -> Optional[Compression]:
        for compression in Compression:
            if compression.value.name == item:
                return compression
        return None

    @staticmethod
    def descriptions() -> List[str]:
        return [f"{compression.value.name}: {compression.value.doc}" for compression in Compression]
