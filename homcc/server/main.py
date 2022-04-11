#!/usr/bin/env python3
"""Executable that is used to start the server."""
import sys
import os

import argparse
import signal

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from homcc.common.logging import (  # pylint: disable=wrong-import-position
    Formatter,
    FormatterConfig,
    FormatterDestination,
    setup_logging,
)
from homcc.server.server import start_server, stop_server  # pylint: disable=wrong-import-position


def main():
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

    def signal_handler(*_):
        stop_server(server)

    signal.signal(signal.SIGINT, signal_handler)
    server_thread.join()


if __name__ == "__main__":
    main()
