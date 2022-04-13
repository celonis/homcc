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
from homcc.client.client_utils import (  # pylint: disable=wrong-import-position
    CompilerError,
    HostsExhaustedError,
    compile_locally,
    compile_remotely,
    scan_includes,
)
from homcc.client.parsing import (  # pylint: disable=wrong-import-position
    NoHostsFoundError,
    load_config_file,
    load_hosts,
    parse_cli_args,
)
from homcc.common.arguments import Arguments  # pylint: disable=wrong-import-position
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
    homcc_config: Dict[str, str] = load_config_file()
    logging_config: Dict[str, int] = {
        "config": FormatterConfig.COLORED,
        "formatter": Formatter.CLIENT,
        "destination": FormatterDestination.STREAM,
    }

    # DEBUG; enable DEBUG mode
    if homcc_args_dict["DEBUG"] or homcc_config.get("DEBUG"):
        logging_config["config"] |= FormatterConfig.DETAILED
        logging_config["level"] = logging.DEBUG

    setup_logging(**logging_config)

    # COMPILER; default: "cc"
    compiler: Optional[str] = compiler_arguments.compiler

    if not compiler:
        compiler = homcc_config.get("compiler", Arguments.default_compiler)
        compiler_arguments.compiler = compiler

    # SCAN-INCLUDES; and exit
    if homcc_args_dict.get("scan_includes"):
        try:
            includes: List[str] = scan_includes(compiler_arguments)
        except CompilerError as e:
            sys.exit(e.returncode)

        for include in includes:
            print(include)

        sys.exit(os.EX_OK)

    # HOST; get host from cli or load hosts from env var or file
    host: Optional[str] = homcc_args_dict.get("host")
    hosts: List[str] = [host] if host else load_hosts()

    # TIMEOUT; default: 180s
    timeout: Optional[float] = homcc_args_dict.get("timeout")

    if not timeout:
        timeout = homcc_config.get("timeout", 180)

    # try to compile remotely
    if compiler_arguments.is_sendable():
        try:
            sys.exit(asyncio.run(compile_remotely(hosts, homcc_config, timeout, compiler_arguments)))

        # exit on unrecoverable errors
        except CompilerError as err:
            sys.exit(err.returncode)

        # compile locally on recoverable errors
        except (HostsExhaustedError, NoHostsFoundError, TCPClientError):
            pass

    # compile locally on recoverable failures or unsendability
    sys.exit(compile_locally(compiler_arguments))


if __name__ == "__main__":
    main()
