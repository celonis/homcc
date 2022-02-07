from homcc.server import *

if __name__ == "__main__":
    port: int = 13337
    server: TCPServer = start_server(port=13337)

    with server:
        input("Press key to exit")
        stop_server(server)
