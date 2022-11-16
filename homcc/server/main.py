#!/usr/bin/env python3
"""Executable that is used to start the server."""
import logging
import os
import signal
import sys
from typing import Any, Dict, Optional

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from homcc import server  # pylint: disable=wrong-import-position
from homcc.common.errors import (  # pylint: disable=wrong-import-position
    ServerInitializationError,
)
from homcc.common.logging import (  # pylint: disable=wrong-import-position
    Formatter,
    FormatterConfig,
    FormatterDestination,
    LoggingConfig,
    LogLevel,
    setup_logging,
)
from homcc.server.parsing import (  # pylint: disable=wrong-import-position
    ServerConfig,
    parse_cli_args,
    parse_config,
)
from homcc.server.server import (  # pylint: disable=wrong-import-position
    start_server,
    stop_server,
)

logger: logging.Logger = logging.getLogger(__name__)


def main():
    # load and parse arguments and configuration information
    homccd_args_dict: Dict[str, Any] = parse_cli_args(sys.argv[1:])

    # prevent config loading and parsing if --no-config was specified
    homccd_config: ServerConfig = ServerConfig.empty() if homccd_args_dict["no_config"] else parse_config()
    logging_config: LoggingConfig = LoggingConfig(
        config=FormatterConfig.COLORED,
        formatter=Formatter.SERVER,
        destination=FormatterDestination.STREAM,
        level=LogLevel.INFO,
    )

    # LOG_LEVEL and VERBOSITY
    log_level: Optional[str] = homccd_args_dict["log_level"]

    # verbosity implies debug mode
    if (
        homccd_args_dict["verbose"]
        or homccd_config.verbose
        or log_level == "DEBUG"
        or homccd_config.log_level == LogLevel.DEBUG
    ):
        logging_config.config |= FormatterConfig.DETAILED
        logging_config.level = logging.DEBUG

    # overwrite verbose debug logging level
    if log_level is not None:
        logging_config.level = LogLevel[log_level].value
    elif homccd_config.log_level is not None:
        logging_config.level = int(homccd_config.log_level)

    setup_logging(logging_config)

    # LIMIT
    if (limit := homccd_args_dict["jobs"]) is not None:
        homccd_config.limit = limit

    # PORT
    if (port := homccd_args_dict["port"]) is not None:
        homccd_config.port = port

    # ADDRESS
    if (address := homccd_args_dict["listen"]) is not None:
        homccd_config.address = address

    # provide additional DEBUG information
    logger.debug(
        "%s - %s\n" "Caller:\t%s\n" "%s",  # homccd location and version; homccd caller; config info
        sys.argv[0],
        server.__version__,
        sys.executable,
        homccd_config,
    )

    # start server
    try:
        tcp_server, server_thread = start_server(homccd_config)
    except ServerInitializationError as error:
        logger.error("Could not start homccd, terminating.")
        raise SystemExit(os.EX_OSERR) from error

    def signal_handler(*_):
        stop_server(tcp_server)

    signal.signal(signal.SIGINT, signal_handler)
    server_thread.join()


if __name__ == "__main__":
    main()
