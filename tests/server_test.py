import socket
from typing import List

from homcc.messages import (
    ArgumentMessage,
    DependencyRequestMessage,
    DependencyReplyMessage,
    CompilationResultMessage,
    Message,
    ObjectFile,
)
from homcc.server import *


class TestServerReceive:
    client_socket: socket.socket
    messages: List[Message] = []
    received_messages: List[Message] = []

    def client_create(self, port):
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client_socket.connect(("localhost", port))

    def client_send(self, bytes):
        self.client_socket.send(bytes)

    def client_stop(self):
        self.client_socket.close()

    def patched_handle_message(self, message: Message):
        self.received_messages.append(message)

    def test_receive_multiple_messages(self):
        # monkey patch the server's handler, so that we can compare
        # messages sent by the client with messages that the server deserialized
        TCPRequestHandler._handle_message = self.patched_handle_message

        server: TCPServer = start_server()
        with server:
            arguments = ["-a", "-b", "--help"]
            cwd = "/home/o.layer/test"
            dependencies = {"server.c": "1239012890312903", "server.h": "testsha1"}
            self.messages.append(ArgumentMessage(arguments, cwd, dependencies))

            self.messages.append(DependencyRequestMessage("asd123"))

            self.messages.append(
                DependencyReplyMessage(
                    "asd123otherHash", bytearray([0x1, 0x2, 0x3, 0x4, 0x5])
                )
            )

            result1 = ObjectFile("foo.o", bytearray([0x1, 0x3, 0x2, 0x4, 0x5, 0x6]))
            result2 = ObjectFile("dir/other_foo.o", bytearray([0xA, 0xFF, 0xAA]))
            self.messages.append(CompilationResultMessage([result1, result2]))

            self.messages.append(
                DependencyReplyMessage("asd123otherHash", bytearray(13337))
            )

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
