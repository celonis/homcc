"""Tests regarding the server."""
import socket
import pytest
from typing import List
from homcc.common.compression import NoCompression

from homcc.common.messages import (
    ArgumentMessage,
    DependencyRequestMessage,
    DependencyReplyMessage,
    CompilationResultMessage,
    Message,
    ObjectFile,
)
from homcc.server.parsing import ServerConfig
from homcc.server.server import start_server, stop_server, TCPRequestHandler


class TestServerReceive:
    """Integration test to test if the server is handling received messages correctly."""

    client_socket: socket.socket
    messages: List[Message] = []
    received_messages: List[Message] = []

    def client_create(self, port):
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client_socket.connect(("localhost", port))

    def client_send(self, bytes_to_send):
        self.client_socket.send(bytes_to_send)

    def client_stop(self):
        self.client_socket.close()

    def patched_handle_message(self, message: Message):
        self.received_messages.append(message)

    @pytest.mark.timeout(1)
    def test_receive_multiple_messages(self, unused_tcp_port):
        # pylint: disable=protected-access
        # justification: needed for monkey patching
        # monkey patch the server's handler, so that we can compare
        # messages sent by the client with messages that the server deserialized
        TCPRequestHandler._handle_message = self.patched_handle_message

        config: ServerConfig = ServerConfig(files=[], address="0.0.0.0", port=unused_tcp_port, limit=1)

        server, _ = start_server(config, schroot_profiles=[])
        with server:
            arguments = ["-a", "-b", "--help"]
            cwd = "/home/o.layer/test"
            dependencies = {"server.c": "1239012890312903", "server.h": "testsha1"}
            self.messages.append(ArgumentMessage(arguments, cwd, dependencies, None, None, NoCompression()))

            self.messages.append(DependencyRequestMessage("asd123"))

            self.messages.append(DependencyReplyMessage(bytearray([0x1, 0x2, 0x3, 0x4, 0x5]), NoCompression()))

            result1 = ObjectFile("foo.o", bytearray([0x1, 0x3, 0x2, 0x4, 0x5, 0x6]), NoCompression())
            result2 = ObjectFile("dir/other_foo.o", bytearray([0xA, 0xFF, 0xAA]), NoCompression())
            self.messages.append(
                CompilationResultMessage([result1, result2], "stdout-foo", "stderr-foo", 0, NoCompression())
            )

            self.messages.append(DependencyReplyMessage(bytearray(13337), NoCompression()))

            _, port = server.server_address
            self.client_create(port)

            for message in self.messages:
                self.client_send(message.to_bytes())

            while len(self.messages) > len(self.received_messages):
                pass

            for received_message in self.received_messages:
                next_message: Message = self.messages.pop(0)
                assert received_message == next_message

            self.client_stop()
            stop_server(server)
