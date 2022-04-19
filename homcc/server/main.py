#!/usr/bin/env python3
"""Executable that is used to start the server."""
import logging
import os
import signal
import sys

from typing import Any, Dict, Optional

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from homcc.common.logging import (  # pylint: disable=wrong-import-position
    Formatter,
    FormatterConfig,
    FormatterDestination,
    LogLevel,
    setup_logging,
)
from homcc.server.parsing import parse_cli_args, parse_config, load_config_file  # pylint: disable=wrong-import-position
from homcc.server.server import TCPServer, start_server, stop_server  # pylint: disable=wrong-import-position

logger: logging.Logger = logging.getLogger(__name__)


def main():
    # load and parse arguments and configuration information
    homccd_args_dict: Dict[str, Any] = parse_cli_args(sys.argv[1:])
    homccd_config: Dict[str, str] = parse_config(load_config_file())
    logging_config: Dict[str, int] = {
        "config": FormatterConfig.COLORED,
        "formatter": Formatter.SERVER,
        "destination": FormatterDestination.STREAM,
    }

    print("HOMCCD ARGS DICT:\n\t", homccd_args_dict)

    # LOG_LEVEL and VERBOSITY
    log_level: str = homccd_args_dict["log_level"]

    if homccd_args_dict["verbose"] or log_level == "DEBUG":
        logging_config["config"] |= FormatterConfig.DETAILED
        logging_config["level"] = logging.DEBUG
    elif log_level:
        logging_config["level"] = LogLevel[homccd_args_dict["log_level"]].value

    setup_logging(**logging_config)

    # LIMIT
    limit: Optional[int] = homccd_args_dict.get("jobs")

    if not limit:
        limit = int(homccd_config.get("limit", TCPServer.DEFAULT_LIMIT))

    # LIFETIME
    lifetime: Optional[float] = homccd_args_dict.get("lifetime")

    if not lifetime:
        lifetime = float(homccd_config.get("lifetime", TCPServer.DEFAULT_LIFETIME))

    # PORT
    port: Optional[int] = homccd_args_dict.get("port")

    if not port:
        port = int(homccd_config.get("port", TCPServer.DEFAULT_PORT))

    # ADDRESS
    address: Optional[str] = homccd_args_dict.get("listen")

    if not address:
        address = homccd_config.get("listen", "localhost")

    # DENYLIST
    denylist: Optional[str] = homccd_args_dict.get("denylist")

    if not denylist:
        denylist = homccd_config.get("denylist")

    # ALLOWLIST
    allowlist: Optional[str] = homccd_args_dict.get("allowlist")

    if not allowlist:
        allowlist = homccd_config.get("allowlist")

    # start server
    server, server_thread = start_server(
        address=address,
        port=port,
        limit=limit,
        lifetime=lifetime,
        denylist=denylist,
        allowlist=allowlist,
    )

    def signal_handler(*_):
        stop_server(server)

    signal.signal(signal.SIGINT, signal_handler)
    server_thread.join()


if __name__ == "__main__":
    main()
