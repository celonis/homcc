"""Main logic for the homcc server."""
import threading
import socketserver
import hashlib
import logging
from tempfile import TemporaryDirectory
from typing import List, Dict, Tuple
from functools import singledispatchmethod

from homcc.common.messages import (
    ArgumentMessage,
    Message,
    DependencyReplyMessage,
    DependencyRequestMessage,
    CompilationResultMessage,
)

from homcc.server.environment import (
    create_root_temp_folder,
    create_instance_folder,
    map_cwd,
    map_arguments,
    get_needed_dependencies,
    map_dependency_paths,
    save_dependency,
    do_compilation,
)

logger = logging.getLogger(__name__)


class TCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    root_temp_folder: TemporaryDirectory

    def __init__(self, server_address, RequestHandlerClass) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.root_temp_folder = create_root_temp_folder()

    def __del__(self) -> None:
        self.root_temp_folder.cleanup()


class TCPRequestHandler(socketserver.BaseRequestHandler):
    """Handles all requests received from the client."""

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
    server: TCPServer
    """The TCP server belonging to this handler. (redefine for typing)"""

    @singledispatchmethod
    def _handle_message(self, message):
        raise NotImplementedError("Unsupported message type.")

    @_handle_message.register
    def _handle_argument_message(self, message: ArgumentMessage):
        logger.info("Handling ArgumentMessage...")

        self.instance_path = create_instance_folder(self.server.root_temp_folder.name)
        logger.info("Created dir for new client: %s", self.instance_path)

        self.mapped_cwd = map_cwd(self.instance_path, message.get_cwd())

        self.compiler_arguments = map_arguments(self.instance_path, self.mapped_cwd, message.get_arguments())
        logger.debug("Mapped compiler args: %s", str(self.compiler_arguments))

        self.mapped_dependencies = map_dependency_paths(self.instance_path, self.mapped_cwd, message.get_dependencies())
        logger.debug("Mapped dependencies: %s", self.mapped_dependencies)

        self.needed_dependencies = get_needed_dependencies(self.mapped_dependencies)
        logger.debug("Needed dependencies: %s", self.needed_dependencies)

        self._request_next_dependency()

    @_handle_message.register
    def _handle_dependency_request_message(self, _: DependencyRequestMessage):
        logger.warning("Received DependencyRequestMessage, but this message is only sent by the server!")

    @_handle_message.register
    def _handle_dependency_reply_message(self, message: DependencyReplyMessage):
        logger.info("Handling DependencyReplyMessage...")
        logger.debug("Len of dependency reply payload is %i", message.get_further_payload_size())

        dependency_content = message.get_content()
        dependency_hash, dependency_path = next(iter(self.needed_dependencies.items()))

        retrieved_dependency_hash = hashlib.sha1(dependency_content).hexdigest()

        # verify that the hashes match
        if dependency_hash != retrieved_dependency_hash:
            logger.error(
                """Assertion failed: Hashes of requested file and received file (path: %s) do not match!
                This should not happen.""",
                dependency_path,
            )
        else:
            del self.needed_dependencies[dependency_hash]
            save_dependency(dependency_path, dependency_content)

        if not self._request_next_dependency():
            # no further dependencies needed, compile now
            result_message = do_compilation(self.instance_path, self.mapped_cwd, self.compiler_arguments)

            self.request.sendall(result_message.to_bytes())

    @_handle_message.register
    def _handle_compilation_result_message(self, _: CompilationResultMessage):
        logger.warning("Received CompilationResultMessage, but this message is only sent by the server!")

    def _request_next_dependency(self) -> bool:
        """Requests a dependency with the given sha1sum from the client.
        Returns False if there is nothing to request any more."""
        if len(self.needed_dependencies) > 0:
            next_needed_hash = next(iter(self.needed_dependencies.keys()))

            request_message = DependencyRequestMessage(next_needed_hash)

            logger.info("Sending request for dependency with hash %s", str(request_message.get_sha1sum()))
            self.request.sendall(request_message.to_bytes())

        return len(self.needed_dependencies) > 0

    def _try_parse_message(self, message_bytes: bytearray) -> int:
        bytes_needed, parsed_message = Message.from_bytes(message_bytes)

        if bytes_needed < 0:
            logger.debug("Received message, but having #%i bytes too much supplied.", abs(bytes_needed))
        elif bytes_needed > 0:
            logger.debug("Supplied buffer does not suffice to parse the message, need further #%i bytes!", bytes_needed)

        if parsed_message is not None:
            logger.debug("Received message of type %s!", parsed_message.message_type)
            self._handle_message(parsed_message)

        return bytes_needed

    def recv(self) -> bytearray:
        """Function that receives from the connection and returns an empty
        bytearray when the connection has been closed."""
        try:
            return self.request.recv(self.BUFFER_SIZE)
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
                        logger.error("Connection closed while only partly received a message. Ungraceful disconnect.")
                        return

                    recv_bytes += further_recv_bytes


def start_server(port: int = 0) -> Tuple[TCPServer, threading.Thread]:
    server: TCPServer = TCPServer(("localhost", port), TCPRequestHandler)

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    return server, server_thread


def stop_server(server: TCPServer):
    server.shutdown()
