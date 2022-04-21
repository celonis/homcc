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
from homcc.server.parsing import (  # pylint: disable=wrong-import-position
    ServerConfig,
    parse_cli_args,
    parse_config,
    load_config_file,
)
from homcc.server.server import start_server, stop_server  # pylint: disable=wrong-import-position

logger: logging.Logger = logging.getLogger(__name__)


def main():
    # load and parse arguments and configuration information
    homccd_args_dict: Dict[str, Any] = parse_cli_args(sys.argv[1:])
    homccd_config: ServerConfig = parse_config(load_config_file())
    logging_config: Dict[str, int] = {
        "config": FormatterConfig.COLORED,
        "formatter": Formatter.SERVER,
        "destination": FormatterDestination.STREAM,
    }

    print("HOMCCD ARGS DICT:\n\t", homccd_args_dict)

    # LOG_LEVEL and VERBOSITY
    log_level: str = homccd_args_dict["log_level"]

    if homccd_args_dict["verbose"] or log_level == "DEBUG" or homccd_config.log_level == LogLevel.DEBUG:
        logging_config["config"] |= FormatterConfig.DETAILED
        logging_config["level"] = logging.DEBUG
    elif log_level:
        logging_config["level"] = LogLevel[homccd_args_dict["log_level"]].value

    setup_logging(**logging_config)

    # LIMIT
    limit: Optional[int] = homccd_args_dict["jobs"] or homccd_config.limit

    # PORT
    port: Optional[int] = homccd_args_dict["port"] or homccd_config.port

    # ADDRESS
    address: Optional[str] = homccd_args_dict["listen"] or homccd_config.address

    # start server
    server, server_thread = start_server(address=address, port=port, limit=limit)

    def signal_handler(*_):
        stop_server(server)

    signal.signal(signal.SIGINT, signal_handler)
    server_thread.join()


if __name__ == "__main__":
    main()
