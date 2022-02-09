from homcc.server import *

if __name__ == "__main__":
    port: int = 3633
    server: TCPServer = start_server(port=port)

    with server:
        input("Press key to exit")
        stop_server(server)
