#!/usr/bin/env python3
"""
homcc client
"""
import asyncio
import logging
import os
import sys

from typing import List

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from homcc.client.compilation import (  # pylint: disable=wrong-import-position
    DEFAULT_LOCALHOST,
    compile_locally,
    compile_remotely,
    scan_includes,
)
from homcc.common.errors import (  # pylint: disable=wrong-import-position
    HostParsingError,
    RecoverableClientError,
    RemoteCompilationError,
)
from homcc.client.parsing import (  # pylint: disable=wrong-import-position
    ClientConfig,
    Host,
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

    # provide additional DEBUG information
    logger.debug(
        "%s - %s\nCalled by: %s\nUsing configuration files: [%s]",
        sys.argv[0],
        "0.0.1",
        sys.executable,
        ", ".join(homcc_config.files),
    )

    # COMPILER; default: "cc"
    if compiler_arguments.compiler is None:
        compiler_arguments.compiler = homcc_config.compiler

    # SCAN-INCLUDES; and exit
    if homcc_args_dict["scan_includes"]:
        for include in scan_includes(compiler_arguments):
            print(include)

        sys.exit(os.EX_OK)

    # HOST; get singular host from cli parameter or load hosts from $HOMCC_HOSTS env var or hosts file
    hosts: List[Host] = []
    localhost: Host = DEFAULT_LOCALHOST

    if (host_str := homcc_args_dict["host"]) is not None:
        hosts = [Host.from_str(host_str)]
    else:
        has_local: bool = False

        for host_str in load_hosts():
            try:
                host: Host = Host.from_str(host_str)
            except HostParsingError as error:
                logger.warning("%s", error)
                continue

            if host.is_local():
                if has_local:
                    logger.warning("Multiple localhost hosts provided!")

                has_local = True
                localhost = host

            hosts.append(host)

        # if no explicit localhost/LIMIT host is provided, add DEFAULT_LOCALHOST host which will limit the amount of
        # locally running compilation jobs
        if not has_local:
            hosts.append(localhost)

    # PROFILE; if --no-profile is specified do not use any specified profiles from cli or config file
    if homcc_args_dict["no_profile"]:
        homcc_config.profile = None
    elif (profile := homcc_args_dict["profile"]) is not None:
        homcc_config.profile = profile

    # TIMEOUT
    if (timeout := homcc_args_dict["timeout"]) is not None:
        homcc_config.timeout = timeout

    # force local compilation on specific conditions
    if compiler_arguments.is_linking_only():  # TODO(s.pirsch): this should probably be removed!
        logger.debug("Linking [%s] to %s", ", ".join(compiler_arguments.object_files), compiler_arguments.output)
        sys.exit(compile_locally(compiler_arguments, localhost))

    if not compiler_arguments.is_sendable():
        sys.exit(compile_locally(compiler_arguments, localhost))

    # try to compile remotely
    try:
        sys.exit(asyncio.run(compile_remotely(compiler_arguments, hosts, homcc_config)))

    # exit on unrecoverable errors
    except RemoteCompilationError as error:
        logger.error("%s", error.message)
        sys.exit(error.return_code)

    # compile locally on recoverable errors
    except RecoverableClientError as error:
        logger.warning("Compiling locally instead (%s):\n%s", error, compiler_arguments)
        sys.exit(compile_locally(compiler_arguments, localhost))


if __name__ == "__main__":
    main()
