"""Main logic for the homcc server."""
import threading
import socketserver
import logging
import random
from tempfile import TemporaryDirectory
from typing import List, Dict, Tuple
from threading import Lock
from functools import singledispatchmethod
from socket import SHUT_RD

from homcc.common.messages import (
    ArgumentMessage,
    ConnectionRefusedMessage,
    Message,
    DependencyReplyMessage,
    DependencyRequestMessage,
    CompilationResultMessage,
)

from homcc.common.hashing import hash_file_with_bytes

from homcc.server.environment import (
    create_root_temp_folder,
    create_instance_folder,
    map_cwd,
    map_arguments,
    get_needed_dependencies,
    map_dependency_paths,
    save_dependency,
    do_compilation,
    symlink_dependency_to_cache,
)

logger = logging.getLogger(__name__)


class TCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    MAX_AMOUNT_CONNECTIONS = 48

    current_amount_connections: int
    """TCP Server instance, holding data relevant across compilations."""
    root_temp_folder: TemporaryDirectory
    cache: Dict[str, str]
    """'Hash' -> 'File path' on server map for holding paths to cached files."""
    cache_mutex: Lock

    def __init__(self, server_address, RequestHandlerClass) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.root_temp_folder = create_root_temp_folder()
        self.current_amount_connections = 0
        self.cache = {}
        self.cache_mutex = Lock()

    def verify_request(self, request, _) -> bool:
        accept_connection = self.current_amount_connections < self.MAX_AMOUNT_CONNECTIONS

        if not accept_connection:
            logger.info(
                "Not accepting new connection, as max limit of #%i connections is already reached.",
                self.MAX_AMOUNT_CONNECTIONS,
            )

            connection_refused_message = ConnectionRefusedMessage()
            request.sendall(connection_refused_message.to_bytes())
            request.shutdown(SHUT_RD)
            request.close()

        return accept_connection

    def __del__(self) -> None:
        self.root_temp_folder.cleanup()


class TCPRequestHandler(socketserver.BaseRequestHandler):
    """Handles all requests received from the client."""

    BUFFER_SIZE = 65536

    mapped_dependencies: Dict[str, str] = {}
    """All dependencies for the current compilation, mapped to server paths."""
    needed_dependencies: Dict[str, str] = {}
    """Further dependencies needed from the client."""
    needed_dependency_keys: List[str] = []
    """Shuffled list of keys for the needed dependencies dict."""
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

        self.needed_dependencies = get_needed_dependencies(
            self.mapped_dependencies, self.server.cache, self.server.cache_mutex
        )
        logger.debug("Needed dependencies: %s", self.needed_dependencies)

        # shuffle the keys so we request them at a different order later to avoid
        # transmitting the same files for simultaneous requests
        self.needed_dependency_keys = list(self.needed_dependencies.keys())
        random.shuffle(self.needed_dependency_keys)

        logger.info(
            "#%i cached dependencies, #%i missing dependencies.",
            len(self.mapped_dependencies) - len(self.needed_dependencies),
            len(self.needed_dependencies),
        )

        self.check_dependencies_exist()

    @_handle_message.register
    def _handle_dependency_request_message(self, _: DependencyRequestMessage):
        logger.warning("Received DependencyRequestMessage, but this message is only sent by the server!")

    @_handle_message.register
    def _handle_dependency_reply_message(self, message: DependencyReplyMessage):
        logger.debug("Handling DependencyReplyMessage...")
        logger.debug("Len of dependency reply payload is %i", message.get_further_payload_size())

        dependency_content = message.get_content()
        dependency_path = next(iter(self.needed_dependency_keys))
        dependency_hash = self.needed_dependencies[dependency_path]

        retrieved_dependency_hash = hash_file_with_bytes(dependency_content)

        # verify that the hashes match
        if dependency_hash != retrieved_dependency_hash:
            logger.error(
                """Assertion failed: Hashes of requested file and received file (path: %s) do not match!
                This should not happen.""",
                dependency_path,
            )
        else:
            del self.needed_dependencies[dependency_path]
            self.needed_dependency_keys.pop(0)

            save_dependency(dependency_path, dependency_content)

            with self.server.cache_mutex:
                self.server.cache[dependency_hash] = dependency_path

        self.check_dependencies_exist()

    @_handle_message.register
    def _handle_compilation_result_message(self, _: CompilationResultMessage):
        logger.warning("Received CompilationResultMessage, but this message is only sent by the server!")

    def _request_next_dependency(self) -> bool:
        """Requests a dependency with the given sha1sum from the client.
        Returns False if there was nothing to request any more."""
        request_sent = False
        while not request_sent and len(self.needed_dependencies) > 0:
            next_needed_file = next(iter(self.needed_dependency_keys))
            next_needed_hash = self.needed_dependencies[next_needed_file]

            with self.server.cache_mutex:
                already_cached = next_needed_hash in self.server.cache

            if already_cached:
                symlink_dependency_to_cache(
                    next_needed_file, next_needed_hash, self.server.cache, self.server.cache_mutex
                )

                del self.needed_dependencies[next_needed_file]
                self.needed_dependency_keys.pop(0)
            else:
                request_message = DependencyRequestMessage(next_needed_hash)

                logger.debug("Sending request for dependency with hash %s", str(request_message.get_sha1sum()))
                self.request.sendall(request_message.to_bytes())
                request_sent = True

        return len(self.needed_dependencies) > 0

    def check_dependencies_exist(self) -> None:
        """Checks if all dependencies exist. If yes, starts compiling. If no, requests missing dependencies."""
        if not self._request_next_dependency():
            # no further dependencies needed, compile now
            result_message = do_compilation(self.instance_path, self.mapped_cwd, self.compiler_arguments)

            self.request.sendall(result_message.to_bytes())

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
        self.server.current_amount_connections += 1
        while True:
            recv_bytes: bytearray = self.recv()

            if len(recv_bytes) == 0:
                logger.info("Connection closed gracefully.")
                self.server.current_amount_connections -= 1
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
                        self.server.current_amount_connections -= 1
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
