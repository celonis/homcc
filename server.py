import socket
import threading
import socketserver
from functools import singledispatchmethod

from messages import (
    ArgumentMessage,
    Message,
    DependencyReplyMessage,
    DependencyRequestMessage,
    CompilationResultMessage,
    ObjectFile,
)


class TCPRequestHandler(socketserver.BaseRequestHandler):
    BUFFER_SIZE = 4096

    @singledispatchmethod
    def _handle_message(self, message):
        raise NotImplementedError("Unsupported message type.")

    @_handle_message.register
    def _(self, message: ArgumentMessage):
        print("Handling ArgumentMessage...")
        pass

    @_handle_message.register
    def _(self, message: DependencyRequestMessage):
        print("Handling DependencyRequestMessage...")
        pass

    @_handle_message.register
    def _(self, message: DependencyReplyMessage):
        print("Handling DependencyReplyMessage...")
        print(
            f"Len of dependency reply payload is {message.get_further_payload_size()}"
        )
        pass

    @_handle_message.register
    def _(self, message: CompilationResultMessage):
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
        else:
            print(
                f"Supplied buffer does not suffice to parse the message, need further #{bytes_needed} bytes!"
            )

        # TODO: handle message
        if parsed_message is not None:
            print(f"Received message of type {parsed_message.message_type}!")
            self._handle_message(parsed_message)
        # response = bytes("{}".format(data), "ascii")
        # self.request.sendall(response)

        return bytes_needed

    def handle(self):
        """Handles incoming requests."""
        recv_bytes: bytearray = self.request.recv(self.BUFFER_SIZE).strip()

        bytes_needed: int = Message.MINIMUM_SIZE_BYTES
        while bytes_needed != 0 or len(recv_bytes) > 0:
            buffer_full = len(recv_bytes) == self.BUFFER_SIZE
            bytes_needed = self._try_parse_message(recv_bytes)

            if bytes_needed < 0:
                # Parsed a message, we still have messages in the buffer.
                # Remove parsed bytes form the buffer.
                recv_bytes = recv_bytes[len(recv_bytes) - abs(bytes_needed) :]
            elif bytes_needed == 0:
                # Buffer contained exactly that parsed message
                recv_bytes = bytearray()
            elif bytes_needed > 0 or buffer_full:
                # Either the buffer has run full (then there is potentially more data waiting for us),
                # or a message is only partly contained in the current buffer and we need more data
                recv_bytes += self.request.recv(self.BUFFER_SIZE).strip()


class TCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass


def client(ip, port, bytes):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((ip, port))
        sock.sendall(bytes)

        print(f"Sending #{len(bytes)} bytes!")


if __name__ == "__main__":
    HOST, PORT = "localhost", 0

    # argument message
    arguments = ["-a", "-b", "--help"]
    cwd = "/home/o.layer/test"
    dependencies = {"server.c": "1239012890312903", "server.h": "testsha1"}
    argument_message = ArgumentMessage(arguments, cwd, dependencies)
    message_bytes = argument_message.to_bytes()
    bytes_needed, parsed_message = Message.from_bytes(message_bytes)

    # DependencyRequestMessage
    dependency_request_message = DependencyRequestMessage("asd123")
    message_bytes = dependency_request_message.to_bytes()
    bytes_needed, parsed_message = Message.from_bytes(message_bytes)

    # DependencyReplyMessage
    dependency_reply_message = DependencyReplyMessage(
        "asd123otherHash", bytearray([0x1, 0x2, 0x3, 0x4, 0x5])
    )
    message_bytes = dependency_reply_message.to_bytes()
    bytes_needed, parsed_message = Message.from_bytes(message_bytes)

    # CompilationResultMessage
    result1 = ObjectFile("foo.o", bytearray([0x1, 0x3, 0x2, 0x4, 0x5, 0x6]))
    result2 = ObjectFile("dir/other_foo.o", bytearray([0xA, 0xFF, 0xAA]))
    compilation_result_message = CompilationResultMessage([result1, result2])
    message_bytes = compilation_result_message.to_bytes()
    bytes_needed, parsed_message = Message.from_bytes(message_bytes)

    # DependencyReplyMessage2
    dependency2_reply_message = DependencyReplyMessage(
        "asd123otherHash", bytearray(13337)
    )
    message_bytes = dependency2_reply_message.to_bytes()
    bytes_needed, parsed_message = Message.from_bytes(message_bytes)

    server = TCPServer((HOST, PORT), TCPRequestHandler)
    with server:
        ip, port = server.server_address

        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        print("Server loop running in thread:", server_thread.name)

        client(
            ip,
            port,
            argument_message.to_bytes()
            + dependency_request_message.to_bytes()
            + dependency_reply_message.to_bytes()
            + compilation_result_message.to_bytes()
            + dependency2_reply_message.to_bytes(),
        )

        input("Press to exit")

        server.shutdown()
