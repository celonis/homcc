#!/usr/bin/env python3
"""Executable that is used to start the server."""
import argparse
import signal

from homcc.common.logging import Formatter, FormatterConfig, FormatterDestination, setup_logging
from homcc.server.server import start_server, stop_server


def signal_handler(*_):
    stop_server(server)


if __name__ == "__main__":
    setup_logging(
        formatter=Formatter.SERVER,
        config=FormatterConfig.COLORED,
        destination=FormatterDestination.STREAM,
    )

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
