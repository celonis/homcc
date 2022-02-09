from typing import List, Dict
import os
from homcc.messages import (
    ArgumentMessage,
    DependencyRequestMessage,
    DependencyReplyMessage,
    CompilationResultMessage,
    Message,
    ObjectFile,
)


class TestArgumentMessage:
    def test_serialization(self):
        arguments: List[str] = ["a", "b", "-c", "--help"]
        cwd: str = "/home/oliver/test123"
        dependencies: Dict[str, str] = {
            "server.c": "1239012890312903",
            "server.h": "testsha1",
        }
        message = ArgumentMessage(arguments, cwd, dependencies)

        message_bytes: bytearray = message.to_bytes()

        _, serialized_message = Message.from_bytes(message_bytes)

        assert message == serialized_message


class TestDependencyRequestMessage:
    def test_serialization(self):
        sha1sum: str = "0a62827cfce18c7da06444d8e8c9eec876a7e65f"
        message = DependencyRequestMessage(sha1sum)

        message_bytes: bytearray = message.to_bytes()

        _, serialized_message = Message.from_bytes(message_bytes)

        assert message == serialized_message


class TestDependencyReplyMessage:
    def test_serialization(self):
        content: bytearray = bytearray(os.urandom(133337))
        message = DependencyReplyMessage(content)

        message_bytes = message.to_bytes()

        _, serialized_message = Message.from_bytes(message_bytes)

        assert message == serialized_message


class TestCompilationResultMessage:
    def test_serialization(self):
        object_files: List[ObjectFile] = []
        for index in range(1, 1337):
            file_name: str = f"dummy_file{index}.o"
            content: bytearray = bytearray(os.urandom(index))
            object_files.append(ObjectFile(file_name, content))

        message = CompilationResultMessage(object_files)

        message_bytes = message.to_bytes()

        _, serialized_message = Message.from_bytes(message_bytes)

        assert message == serialized_message
