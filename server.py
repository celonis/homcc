import logging

from homcc.server.server import *

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    port: int = 3633
    server: TCPServer = start_server(port=port)

    with server:
        input("Press key to exit\n")
        stop_server(server)
