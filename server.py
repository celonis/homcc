from asyncio import start_server
from homcc.server import *

if __name__ == "__main__":
    port: int = 13337
    server: TCPServer = start_server(port=13337)

    with server:
        # TODO: logging
        # TODO: parameters for e.g. specifying port
        # TODO: add signal catcher to shutdown upon received signal
        input("Press key to exit")
        stop_server(server)
