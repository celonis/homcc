#!/usr/bin/env python3
"""
homcc client
"""
import asyncio
import logging
import os
import sys

from typing import List, Optional

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from homcc.client.compilation import (  # pylint: disable=wrong-import-position
    compile_locally,
    compile_remotely,
    scan_includes,
)
from homcc.client.errors import RecoverableClientError, RemoteCompilationError  # pylint: disable=wrong-import-position
from homcc.client.parsing import (  # pylint: disable=wrong-import-position
    ClientConfig,
    LogLevel,
    load_hosts,
    parse_cli_args,
    parse_config,
)
from homcc.common.logging import (  # pylint: disable=wrong-import-position
    Formatter,
    FormatterConfig,
    FormatterDestination,
    LoggingConfig,
    setup_logging,
)

logger: logging.Logger = logging.getLogger(__name__)


def main():
    # load and parse arguments and configuration information
    homcc_args_dict, compiler_arguments = parse_cli_args(sys.argv[1:])
    homcc_config: ClientConfig = parse_config()
    logging_config: LoggingConfig = LoggingConfig(
        config=FormatterConfig.COLORED,
        formatter=Formatter.CLIENT,
        destination=FormatterDestination.STREAM,
    )

    # LOG_LEVEL and VERBOSITY
    log_level: str = homcc_args_dict["log_level"]

    # verbosity implies debug mode
    if (
        homcc_args_dict["verbose"]
        or homcc_config.verbose
        or log_level == "DEBUG"
        or homcc_config.log_level == LogLevel.DEBUG
    ):
        logging_config.config |= FormatterConfig.DETAILED
        logging_config.level = logging.DEBUG

    # overwrite verbose debug logging level
    if log_level is not None:
        logging_config.level = LogLevel[log_level].value
    elif homcc_config.log_level is not None:
        logging_config.level = int(homcc_config.log_level)

    setup_logging(logging_config)

    # COMPILER; default: "cc"
    if compiler_arguments.compiler is None:
        compiler_arguments.compiler = homcc_config.compiler

    # SCAN-INCLUDES; and exit
    if homcc_args_dict["scan_includes"]:
        for include in scan_includes(compiler_arguments):
            print(include)

        sys.exit(os.EX_OK)

    # HOST; get host from cli or load hosts from env var or file
    host: Optional[str] = homcc_args_dict["host"]
    hosts: List[str] = [host] if host else load_hosts()

    # PROFILE; if --no-profile was specified do not use profile from cli or config file
    profile: Optional[str] = homcc_args_dict["profile"]

    if homcc_args_dict["no_profile"]:
        homcc_config.profile = None
    elif profile:
        homcc_config.profile = profile

    # TIMEOUT
    timeout: Optional[float] = homcc_args_dict["timeout"]

    if timeout:
        homcc_config.timeout = timeout

    if compiler_arguments.is_linking_only():
        logger.debug("Linking [%s] to %s", ", ".join(compiler_arguments.object_files), compiler_arguments.output)
        sys.exit(compile_locally(compiler_arguments))

    # try to compile remotely
    if compiler_arguments.is_sendable():
        try:
            sys.exit(asyncio.run(compile_remotely(compiler_arguments, hosts, homcc_config)))

        # exit on unrecoverable errors
        except RemoteCompilationError as error:
            logger.error("%s", error.message)
            # sys.exit(error.return_code)

            # TODO(s.pirsch): remove local compilation fallback after extensive testing, disable for benchmarking!
            # for now, we try to recover from remote compilation errors via local compilation to track bugs
            local_compilation_return_code: int = compile_locally(compiler_arguments)
            if local_compilation_return_code != error.return_code:
                logger.critical(
                    "Different compilation result errors: Client error(%i) - Host error(%i)",
                    local_compilation_return_code,
                    error.return_code,
                )
            sys.exit(local_compilation_return_code)

        # compile locally on recoverable errors
        except RecoverableClientError as error:
            logger.warning("%s", error)

    # compile locally on unsendable arguments
    logger.warning("Compiling locally instead:\n%s", compiler_arguments)
    sys.exit(compile_locally(compiler_arguments))


if __name__ == "__main__":
    main()
