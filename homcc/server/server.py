import threading
import socketserver
import hashlib
import logging
from typing import List, Dict, Tuple
from functools import singledispatchmethod

from homcc.messages import (
    ArgumentMessage,
    Message,
    DependencyReplyMessage,
    DependencyRequestMessage,
    CompilationResultMessage,
)
from homcc.server.environment import *

logger = logging.getLogger(__name__)


class TCPRequestHandler(socketserver.BaseRequestHandler):
    BUFFER_SIZE = 4096

    mapped_dependencies: Dict[str, str] = {}
    """All dependencies for the current compilation, mapped to server paths."""
    needed_dependencies: Dict[str, str] = {}
    """Further dependencies needed from the client."""
    compiler_arguments: List[str] = []
    """List of compiler arguments."""
    instance_path: str = ""
    """Path to the current compilation inside /tmp/."""
    mapped_cwd: str = ""
    """Absolute path to the working directory."""

    @singledispatchmethod
    def _handle_message(self, message):
        raise NotImplementedError("Unsupported message type.")

    @_handle_message.register
    def _handle_argument_message(self, message: ArgumentMessage):
        logger.info("Handling ArgumentMessage...")

        self.instance_path = create_instance_folder()
        logger.debug(f"Created dir {self.instance_path}")

        self.mapped_cwd = map_cwd(self.instance_path, message.get_cwd())

        self.compiler_arguments = map_arguments(
            self.instance_path, self.mapped_cwd, message.get_arguments()
        )
        logger.debug(f"Mapped compiler args: {str(self.compiler_arguments)}")

        self.mapped_dependencies = map_dependency_paths(
            self.instance_path, self.mapped_cwd, message.get_dependencies()
        )
        logger.debug(f"Mapped dependencies: {self.mapped_dependencies}")

        self.needed_dependencies = get_needed_dependencies(self.mapped_dependencies)
        logger.debug(f"Needed dependencies: {self.needed_dependencies}")

        self._request_next_dependency()

    @_handle_message.register
    def _handle_dependency_request_message(self, message: DependencyRequestMessage):
        logger.warn(
            "Received DependencyRequestMessage, but this message is only sent by the server!"
        )

    @_handle_message.register
    def _handle_dependency_reply_message(self, message: DependencyReplyMessage):
        logger.info("Handling DependencyReplyMessage...")
        logger.debug(
            f"Len of dependency reply payload is {message.get_further_payload_size()}"
        )

        dependency_content = message.get_content()
        dependency_path, dependency_hash = next(iter(self.needed_dependencies.items()))

        retrieved_dependency_hash = hashlib.sha1(dependency_content).hexdigest()

        # assertion: verify that the hashes match
        if dependency_hash != retrieved_dependency_hash:
            logger.error(
                "Assertion failed: Hashes of requested file and received file do not match!"
            )
            # TODO: think about handling this
            exit(1)

        del self.needed_dependencies[dependency_path]

        save_dependency(dependency_path, dependency_content)

        if not self._request_next_dependency():
            # no further dependencies needed, compile now
            object_files = compile(self.mapped_cwd, self.compiler_arguments)
            result_message = CompilationResultMessage(object_files)
            self.request.sendall(result_message.to_bytes())

    @_handle_message.register
    def _handle_compilation_result_message(self, message: CompilationResultMessage):
        logger.warn(
            "Received CompilationResultMessage, but this message is only sent by the server!"
        )

    def _request_next_dependency(self) -> bool:
        """Requests a dependency with the given sha1sum from the client.
        Returns False if there is nothing to request any more."""
        if len(self.needed_dependencies) > 0:
            next_needed_hash = next(iter(self.needed_dependencies.values()))

            request_message = DependencyRequestMessage(next_needed_hash)

            logger.info(
                f"Sending request for dependency with hash {str(request_message.get_sha1sum())}"
            )
            self.request.sendall(request_message.to_bytes())

        return len(self.needed_dependencies) > 0

    def _try_parse_message(self, bytes: bytearray) -> int:
        bytes_needed, parsed_message = Message.from_bytes(bytes)

        if bytes_needed < 0:
            logger.debug(
                f"Received message, but having #{abs(bytes_needed)} bytes too much supplied."
            )
        elif bytes_needed > 0:
            logger.debug(
                f"Supplied buffer does not suffice to parse the message, need further #{bytes_needed} bytes!"
            )

        if parsed_message is not None:
            logger.debug(f"Received message of type {parsed_message.message_type}!")
            self._handle_message(parsed_message)

        return bytes_needed

    def recv(self) -> bytearray:
        """Function that receives from the connection and returns an empty
        bytearray when the connection has been closed."""
        try:
            return self.request.recv(self.BUFFER_SIZE).strip()
        except ConnectionError:
            return bytearray()

    def handle(self):
        """Handles incoming requests. Returning from this functions means
        that the connection will be closed from the server side."""
        while True:
            recv_bytes: bytearray = self.recv()

            if len(recv_bytes) == 0:
                logger.info("Connection closed gracefully.")
                return

            bytes_needed: int = Message.MINIMUM_SIZE_BYTES
            while bytes_needed != 0 and len(recv_bytes) > 0:
                bytes_needed = self._try_parse_message(recv_bytes)

                if bytes_needed < 0:
                    # Parsed a message, we still have further messages in the buffer.
                    # Remove parsed bytes form the buffer.
                    recv_bytes = recv_bytes[len(recv_bytes) - abs(bytes_needed) :]
                elif bytes_needed > 0:
                    # A message is only partly contained in the current buffer and we need more data
                    further_recv_bytes = self.recv()

                    if len(further_recv_bytes) == 0:
                        logger.error(
                            "Connection closed while only partly received a message. Ungraceful disconnect."
                        )
                        return

                    recv_bytes += further_recv_bytes


class TCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass


def start_server(port: int = 0) -> Tuple[TCPServer, threading.Thread]:
    server: TCPServer = TCPServer(("localhost", port), TCPRequestHandler)

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    return server, server_thread


def stop_server(server: TCPServer):
    server.shutdown()
