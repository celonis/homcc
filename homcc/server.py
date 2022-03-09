import threading
import socketserver
from functools import singledispatchmethod

from homcc.messages import (
    ArgumentMessage,
    Message,
    DependencyReplyMessage,
    DependencyRequestMessage,
    CompilationResultMessage,
)


class TCPRequestHandler(socketserver.BaseRequestHandler):
    BUFFER_SIZE = 4096

    @singledispatchmethod
    def _handle_message(self, message):
        raise NotImplementedError("Unsupported message type.")

    @_handle_message.register
    def _handle_argument_message(self, message: ArgumentMessage):
        print("Handling ArgumentMessage...")
        pass

    @_handle_message.register
    def _handle_dependency_request_message(self, message: DependencyRequestMessage):
        print("Handling DependencyRequestMessage...")
        pass

    @_handle_message.register
    def _handle_dependency_reply_message(self, message: DependencyReplyMessage):
        print("Handling DependencyReplyMessage...")
        print(
            f"Len of dependency reply payload is {message.get_further_payload_size()}"
        )
        pass

    @_handle_message.register
    def _handle_compilation_result_message(self, message: CompilationResultMessage):
        print("Handling CompilationResultMessage...")
        print(
            f"Len of compilation result payload is {message.get_further_payload_size()}"
        )
        pass

    def _try_parse_message(self, bytes: bytearray) -> int:
        bytes_needed, parsed_message = Message.from_bytes(bytes)

        if bytes_needed < 0:
            print(
                f"Received message, but having #{abs(bytes_needed)} bytes too much supplied."
            )
        elif bytes_needed > 0:
            print(
                f"Supplied buffer does not suffice to parse the message, need further #{bytes_needed} bytes!"
            )

        if parsed_message is not None:
            print(f"Received message of type {parsed_message.message_type}!")
            self._handle_message(parsed_message)

        return bytes_needed

    def handle(self):
        """Handles incoming requests. Returning from this functions means
        that the connection will be closed from the server side."""
        while True:
            recv_bytes: bytearray = self.request.recv(self.BUFFER_SIZE).strip()

            if len(recv_bytes) == 0:
                print("Connection closed gracefully.")
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
                    further_recv_bytes: bytearray = self.request.recv(
                        self.BUFFER_SIZE
                    ).strip()

                    if len(further_recv_bytes) == 0:
                        print(
                            "Connection closed while only partly received a message. Ungraceful disconnect."
                        )
                        return

                    recv_bytes += further_recv_bytes


class TCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass


def start_server(port: int = 0) -> TCPServer:
    server: TCPServer = TCPServer(("localhost", port), TCPRequestHandler)

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    return server


def stop_server(server: TCPServer):
    server.shutdown()