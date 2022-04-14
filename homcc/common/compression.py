"""Compression related functionality"""
from __future__ import annotations

from enum import Enum
from typing import Any, Callable, List, Optional


def lzo(data: bytes, compress: bool) -> bytes:
    """Lempel–Ziv–Oberhumer compression algorithm"""
    raise NotImplementedError


def lzma(data: bytes, compress: bool) -> bytes:
    """Lempel–Ziv–Markov chain algorithm"""
    raise NotImplementedError


class _FunctionWrapper:
    """
    Wrapper for compression functions to allow callable storage in the Compression Enum and easy access to their name
    and doc strings
    """

    def __init__(self, function: Callable[[bytes, bool], bytes]):
        self.function = function
        self.name: str = function.__name__

        if not function.__doc__:
            raise ValueError(f"Function {self.name} must have a doc string!")

        self.doc: str = function.__doc__

    def __call__(self, data: bytes, compress: bool) -> bytes:
        return self.function(data, compress)


class Compression(Enum):
    """Enum class of all supported compression types"""

    LZO = _FunctionWrapper(lzo)
    LZMA = _FunctionWrapper(lzma)

    def __call__(self, data: bytes, compress: bool) -> bytes:
        return self.value(data, compress)

    def __str__(self) -> str:
        return self.value.name

    @staticmethod
    def get(item: str, default: Any = None) -> Optional[Compression]:
        for compression in Compression:
            if compression.value.name == item:
                return compression
        return default

    @staticmethod
    def descriptions() -> List[str]:
        return [f"{compression.value.name}: {compression.value.doc}" for compression in Compression]
