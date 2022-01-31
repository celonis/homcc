import socket
import threading
import socketserver

from messages import ArgumentMessage, Message

# TODO: change TCP request handler and server accordingly, so that messages are sent
# TODO: try other message types


class TCPRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data = str(self.request.recv(1024), "ascii")
        response = bytes("{}".format(data), "ascii")
        self.request.sendall(response)


class TCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass


def client(ip, port, message):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((ip, port))
        sock.sendall(bytes(message, "ascii"))
        response = str(sock.recv(1024), "ascii")
        print("Received: {}".format(response))


if __name__ == "__main__":
    HOST, PORT = "localhost", 0

    arguments = ["-a", "-b", "--help"]
    cwd = "/home/o.layer/test"
    dependencies = {"server.c": "1239012890312903", "server.h": "testsha1"}
    message = ArgumentMessage(arguments, cwd, dependencies)
    message_bytes = message.to_bytes()
    bytes_needed, parsed_message = Message.from_bytes(message_bytes)

    server = TCPServer((HOST, PORT), TCPRequestHandler)
    with server:
        ip, port = server.server_address

        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        print("Server loop running in thread:", server_thread.name)

        client(ip, port, "Hello World 1")
        client(ip, port, "Hello World 2")
        client(ip, port, "Hello World 3")

        server.shutdown()
