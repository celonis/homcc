"""Tests regarding the server."""
import socket
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from pytest_mock import MockerFixture

from homcc.common.compression import NoCompression
from homcc.common.messages import (
    ArgumentMessage,
    CompilationResultMessage,
    DependencyReplyMessage,
    DependencyRequestMessage,
    Message,
    File,
)
from homcc.server.parsing import ServerConfig
from homcc.server.server import TCPRequestHandler, start_server, stop_server


class TestServer:
    """Tests the Server class."""

    @pytest.fixture(autouse=True)
    def setup_mock(self):
        self.request_handler = TCPRequestHandler.__new__(TCPRequestHandler)
        self.request_handler.server = MagicMock()
        self.request_handler.request = MagicMock()

    def test_check_compiler_arguments(self, mocker: MockerFixture):
        mocker.patch(
            "homcc.server.environment.Environment.compiler_exists",
            return_value=False,
        )

        arguments = MagicMock()
        with patch.object(self.request_handler, "close_connection") as mocked_close_connection:
            assert not self.request_handler.check_compiler_arguments(arguments)
            mocked_close_connection.assert_called_once()

        mocker.patch(
            "homcc.server.environment.Environment.compiler_exists",
            return_value=True,
        )
        with patch.object(self.request_handler, "close_connection") as mocked_close_connection:
            assert self.request_handler.check_compiler_arguments(arguments)
            mocked_close_connection.assert_not_called()

    def test_check_target_argument(self, mocker: MockerFixture):
        mocker.patch(
            "homcc.server.environment.Environment.compiler_supports_target",
            return_value=False,
        )

        arguments = MagicMock()
        with patch.object(self.request_handler, "close_connection") as mocked_close_connection:
            assert not self.request_handler.check_target_argument(arguments, "some_target")
            mocked_close_connection.assert_called_once()

        mocker.patch(
            "homcc.server.environment.Environment.compiler_supports_target",
            return_value=True,
        )
        with patch.object(self.request_handler, "close_connection") as mocked_close_connection:
            assert self.request_handler.check_target_argument(arguments, "some_target")
            mocked_close_connection.assert_not_called()

    def test_check_docker_container_argument(self, mocker: MockerFixture):
        mocker.patch(
            "homcc.server.server.is_docker_available",
            return_value=False,
        )
        with patch.object(self.request_handler, "close_connection") as mocked_close_connection:
            assert not self.request_handler.check_docker_container_argument("some_container")
            mocked_close_connection.assert_called_once()

        mocker.patch(
            "homcc.server.server.is_docker_available",
            return_value=True,
        )
        mocker.patch(
            "homcc.server.server.is_valid_docker_container",
            return_value=False,
        )
        with patch.object(self.request_handler, "close_connection") as mocked_close_connection:
            assert not self.request_handler.check_docker_container_argument("some_container")
            mocked_close_connection.assert_called_once()

        mocker.patch(
            "homcc.server.server.is_valid_docker_container",
            return_value=True,
        )
        with patch.object(self.request_handler, "close_connection") as mocked_close_connection:
            assert self.request_handler.check_docker_container_argument("some_container")
            mocked_close_connection.assert_not_called()

    def test_check_schroot_profile_argument(self, mocker: MockerFixture):
        mocker.patch(
            "homcc.server.server.get_schroot_profiles",
            return_value=[],
        )
        mocker.patch(
            "homcc.server.server.is_schroot_available",
            return_value=False,
        )
        with patch.object(self.request_handler, "close_connection") as mocked_close_connection:
            assert not self.request_handler.check_schroot_profile_argument("some_profile")
            mocked_close_connection.assert_called_once()

        mocker.patch(
            "homcc.server.server.is_schroot_available",
            return_value=True,
        )
        mocker.patch(
            "homcc.server.server.is_valid_schroot_profile",
            return_value=False,
        )
        with patch.object(self.request_handler, "close_connection") as mocked_close_connection:
            assert not self.request_handler.check_schroot_profile_argument("some_profile")
            mocked_close_connection.assert_called_once()

        mocker.patch(
            "homcc.server.server.is_valid_schroot_profile",
            return_value=True,
        )
        with patch.object(self.request_handler, "close_connection") as mocked_close_connection:
            assert self.request_handler.check_schroot_profile_argument("some_profile")
            mocked_close_connection.assert_not_called()


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

        server, _ = start_server(config)
        with server:
            arguments = ["-a", "-b", "--help"]
            cwd = "/home/o.layer/test"
            dependencies = {"server.c": "1239012890312903", "server.h": "testsha1"}
            self.messages.append(ArgumentMessage(arguments, cwd, dependencies, None, None, None, NoCompression()))

            self.messages.append(DependencyRequestMessage("asd123"))

            self.messages.append(DependencyReplyMessage(bytearray([0x1, 0x2, 0x3, 0x4, 0x5]), NoCompression()))

            object_file1 = File("foo.o", bytearray([0x1, 0x3, 0x2, 0x4, 0x5, 0x6]), NoCompression())
            object_file2 = File("dir/other_foo.o", bytearray([0xA, 0xFF, 0xAA]), NoCompression())

            dwarf_file1 = File("foo.dwo", bytearray([0x0, 0x1, 0x2, 0x5, 0x5, 0x6]), NoCompression())
            dwarf_file2 = File("dir/other_foo.dwo", bytearray([0xB, 0xCC, 0xAA]), NoCompression())

            self.messages.append(
                CompilationResultMessage(
                    [object_file1, object_file2],
                    "stdout-foo",
                    "stderr-foo",
                    0,
                    NoCompression(),
                    [dwarf_file1, dwarf_file2],
                )
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
