"""Compression related functionality"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, List, Type

import lzma
import lzo  # type: ignore
import logging

logger = logging.getLogger(__name__)


class CompressedBytes:
    """Class that holds (compressed) bytes."""

    data: bytearray
    """Uncompressed data."""
    compressed_data: Optional[bytearray]
    """Compressed data. Field is only written when compressed data is requested and acts as a cache."""

    def __init__(self, data: bytearray, compression: Compression) -> None:
        self.compression = compression
        self.data = data
        self.compressed_data = None

    def __len__(self):
        compressed = self.to_wire()
        return len(compressed)

    def get_data(self) -> bytearray:
        """Returns the uncompressed data."""
        return self.data

    def to_wire(self) -> bytearray:
        """Returns the compressed data (so called 'wire format')."""
        if self.compressed_data:
            return self.compressed_data

        self.compressed_data = self.compression.compress(self.data)
        return self.compressed_data

    @staticmethod
    def from_wire(data: bytearray, compression: Compression) -> CompressedBytes:
        """Creates an object from data in the wire format."""
        return CompressedBytes(compression.decompress(data), compression)

    def __eq__(self, other) -> bool:
        if isinstance(other, CompressedBytes):
            return self.data == other.data and self.compression == other.compression

        return False


class Compression(ABC):
    """Base class for compression algorithms"""

    @staticmethod
    def from_name(name: str) -> Compression:
        for algorithm in Compression.algorithms():
            if algorithm.name() == name:
                return algorithm()

        raise ValueError(f"No compression algorithm with name {name}!")

    @abstractmethod
    def compress(self, data: bytearray) -> bytearray:
        pass

    @abstractmethod
    def decompress(self, data: bytearray) -> bytearray:
        pass

    @staticmethod
    @abstractmethod
    def name() -> str:
        pass

    @staticmethod
    def descriptions() -> List[str]:
        return [
            f"{str(compression.name())}: {compression.__doc__}"
            for compression in Compression.algorithms(without_no_compression=True)
        ]

    @staticmethod
    def algorithms(without_no_compression: bool = False) -> List[Type[Compression]]:
        algorithms = Compression.__subclasses__()

        if without_no_compression:
            algorithms.remove(NoCompression)
        return algorithms

    def __str__(self) -> str:
        return self.name()

    def __eq__(self, other) -> bool:
        if isinstance(other, Compression):
            return self.name() == other.name()
        return False


class NoCompression(Compression):
    """Class that represents no compression, i.e. the identity function."""

    def compress(self, data: bytearray) -> bytearray:
        return data

    def decompress(self, data: bytearray) -> bytearray:
        return data

    @staticmethod
    def name() -> str:
        return "no_compression"


class LZO(Compression):
    """Lempel-Ziv-Oberhumer compression algorithm"""

    def compress(self, data: bytearray) -> bytearray:
        compressed_data = bytearray(lzo.compress(bytes(data)))
        logger.debug("LZO: Compressed #%i bytes to #%i bytes.", len(data), len(compressed_data))
        return compressed_data

    def decompress(self, data: bytearray) -> bytearray:
        decompressed_data = bytearray(lzo.decompress(bytes(data)))
        logger.debug("LZO: Decompressed #%i bytes to #%i bytes.", len(data), len(decompressed_data))
        return decompressed_data

    @staticmethod
    def name() -> str:
        return "lzo"


class LZMA(Compression):
    """Lempel-Ziv-Markov chain algorithm"""

    def compress(self, data: bytearray) -> bytearray:
        compressed_data = bytearray(lzma.compress(data))
        logger.debug("LZMA: Compressed #%i bytes to #%i bytes.", len(data), len(compressed_data))
        return compressed_data

    def decompress(self, data: bytearray) -> bytearray:
        decompressed_data = bytearray(lzma.decompress(data))
        logger.debug("LZMA: Decompressed #%i bytes to #%i bytes.", len(data), len(decompressed_data))
        return decompressed_data

    @staticmethod
    def name() -> str:
        return "lzma"
