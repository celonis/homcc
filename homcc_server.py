"""Executable that is used to start the server."""
import logging
import argparse
import signal

from homcc.server.server import start_server, stop_server


def signal_handler(*_):
    stop_server(server)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="homcc server for compiling cpp files from home.")
    parser.add_argument(
        "--port",
        required=False,
        default=3633,
        type=int,
        help="Port to listen to incoming connections",
    )

    args = parser.parse_args()

    server, server_thread = start_server(port=args.port)
    signal.signal(signal.SIGINT, signal_handler)
    server_thread.join()
