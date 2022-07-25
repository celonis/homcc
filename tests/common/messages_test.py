"""Tests the messages module of homcc."""
import pytest

from typing import List, Dict
import os
from homcc.common.messages import (
    ArgumentMessage,
    DependencyRequestMessage,
    DependencyReplyMessage,
    CompilationResultMessage,
    Message,
    ObjectFile,
)
from homcc.common.compression import LZMA, NoCompression


class TestArgumentMessage:
    """Tests related to the ArgumentMessage."""

    def test_serialization(self):
        arguments: List[str] = ["a", "b", "-c", "--help"]
        cwd: str = "/home/oliver/test123"
        dependencies: Dict[str, str] = {
            "server.c": "1239012890312903",
            "server.h": "testsha1",
        }
        message = ArgumentMessage(
            arguments,
            cwd,
            dependencies,
            target="target",
            schroot_profile="foobar",
            docker_container=None,
            compression=LZMA(),
        )

        message_bytes: bytearray = message.to_bytes()

        _, serialized_message = Message.from_bytes(message_bytes)

        assert message == serialized_message


class TestDependencyRequestMessage:
    """Tests related to the DependencyRequestMessage."""

    def test_serialization(self):
        sha1sum: str = "0a62827cfce18c7da06444d8e8c9eec876a7e65f"
        message = DependencyRequestMessage(sha1sum)

        message_bytes: bytearray = message.to_bytes()

        _, serialized_message = Message.from_bytes(message_bytes)

        assert message == serialized_message


class TestDependencyReplyMessage:
    """Tests related to the DependencyReplyMessage."""

    def test_serialization(self):
        content: bytearray = bytearray(os.urandom(133337))
        message = DependencyReplyMessage(content, LZMA())

        message_bytes = message.to_bytes()

        _, serialized_message = Message.from_bytes(message_bytes)

        assert message == serialized_message


class TestCompilationResultMessage:
    """Tests related to the CompilationResultMessage."""

    def test_serialization(self):
        object_files: List[ObjectFile] = []
        for index in range(1, 1337):
            file_name: str = f"dummy_file{index}.o"
            content: bytearray = bytearray(os.urandom(index))
            object_files.append(ObjectFile(file_name, content, LZMA()))

        message = CompilationResultMessage(object_files, "some", "", 137, LZMA())
        message_bytes = message.to_bytes()

        _, serialized_message = Message.from_bytes(message_bytes)

        assert message == serialized_message


class TestObjectFile:
    """Tests related to the ObjectFile data structure"""

    test_data = bytearray([0x1, 0x2, 0x3])

    def test_content_object_file(self):
        object_file = ObjectFile("foo.o", self.test_data, NoCompression())

        assert object_file.get_data() == self.test_data
        assert len(object_file) == len(self.test_data)
        assert object_file.to_wire() == self.test_data

    def test_size_object_file(self):
        object_file = ObjectFile("foo.o", None, NoCompression(), size=33)

        assert len(object_file) == 33
        with pytest.raises(ValueError):
            object_file.get_data()

    def test_compressed_object_file(self):
        compressed_data = LZMA().compress(self.test_data)
        object_file = ObjectFile("foo.o", self.test_data, LZMA())

        assert len(object_file) == len(compressed_data)
        assert object_file.to_wire() == compressed_data
