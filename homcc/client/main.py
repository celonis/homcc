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
    config: Dict[str, str] = load_config_file()

    # DEBUG; enable DEBUG mode
    if homcc_args_dict["DEBUG"] or config.get("DEBUG"):
        setup_logging(
            formatter=Formatter.CLIENT,
            config=FormatterConfig.COLORED,
            destination=FormatterDestination.STREAM,
        )

    logger.debug("homcc args:\n%s\ncompiler args:\n%s", homcc_args_dict, compiler_arguments)
    logger.debug("config:%s", config)

    # COMPILER; default: "cc"
    compiler: Optional[str] = compiler_arguments.compiler

    if not compiler:
        compiler = config.get("compiler", Arguments.default_compiler)
        compiler_arguments.compiler = compiler

    # SCAN-INCLUDES; and exit
    if homcc_args_dict.get("scan_includes"):
        sys.exit(scan_includes(compiler_arguments))

    # HOST; get host from cli or load hosts from env var or file
    host: Optional[str] = homcc_args_dict.get("host")
    hosts: List[str] = [host] if host else load_hosts()

    # TIMEOUT; default: 180s
    timeout: Optional[float] = homcc_args_dict.get("timeout")

    if not timeout:
        timeout = config.get("timeout", 180)

    if compiler_arguments.is_sendable():
        # try to compile remotely
        try:
            sys.exit(asyncio.run(compile_remotely(hosts, config, timeout, compiler_arguments)))

        # exit on unrecoverable errors
        except CompilerError as err:
            sys.exit(err.returncode)

        # compile locally on recoverable errors
        except (NoHostsFoundError, TCPClientError):
            pass

    # compile locally
    sys.exit(compile_locally(compiler_arguments))


if __name__ == "__main__":
    main()
