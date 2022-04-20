#!/usr/bin/env python3
"""
homcc client
"""
import asyncio
import logging
import os
import sys

from typing import Dict, List, Optional

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from homcc.client.client import TCPClientError  # pylint: disable=wrong-import-position
from homcc.client.compilation import (  # pylint: disable=wrong-import-position
    CompilerError,
    HostsExhaustedError,
    compile_locally,
    compile_remotely,
    scan_includes,
)
from homcc.client.parsing import (  # pylint: disable=wrong-import-position
    ClientConfig,
    NoHostsFoundError,
    load_config_file,
    load_hosts,
    parse_cli_args,
    parse_config,
)
from homcc.common.logging import (  # pylint: disable=wrong-import-position
    Formatter,
    FormatterConfig,
    FormatterDestination,
    setup_logging,
)

logger: logging.Logger = logging.getLogger(__name__)


def main():
    # load and parse arguments and configuration information
    homcc_args_dict, compiler_arguments = parse_cli_args(sys.argv[1:])
    client_config: ClientConfig = parse_config(load_config_file())
    logging_config: Dict[str, int] = {
        "config": FormatterConfig.COLORED,
        "formatter": Formatter.CLIENT,
        "destination": FormatterDestination.STREAM,
    }

    # VERBOSE; enables verbose mode
    if homcc_args_dict["verbose"] or client_config.verbose:
        logging_config["config"] |= FormatterConfig.DETAILED
        logging_config["level"] = logging.DEBUG

    setup_logging(**logging_config)

    # COMPILER; default: "cc"
    compiler: Optional[str] = compiler_arguments.compiler

    if not compiler:
        compiler = client_config.compiler
        compiler_arguments.compiler = compiler

    # SCAN-INCLUDES; and exit
    if homcc_args_dict["scan_includes"]:
        try:
            includes: List[str] = scan_includes(compiler_arguments)
        except CompilerError as e:
            sys.exit(e.returncode)

        for include in includes:
            print(include)

        sys.exit(os.EX_OK)

    # HOST; get host from cli or load hosts from env var or file
    host: Optional[str] = homcc_args_dict["host"]
    hosts: List[str] = [host] if host else load_hosts()

    # TIMEOUT
    timeout: Optional[float] = homcc_args_dict["timeout"]

    if timeout:
        client_config.timeout = timeout

    # try to compile remotely
    if compiler_arguments.is_sendable():
        try:
            sys.exit(asyncio.run(compile_remotely(hosts, client_config, compiler_arguments)))

        # exit on unrecoverable errors
        except CompilerError as error:
            sys.exit(error.returncode)

        # recoverable errors
        except (HostsExhaustedError, NoHostsFoundError, TCPClientError) as error:
            logger.warning("%s", error)

    # compile locally on unsendable arguments or recoverable errors
    sys.exit(compile_locally(compiler_arguments))


if __name__ == "__main__":
    main()
