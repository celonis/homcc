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

from homcc import client  # pylint: disable=wrong-import-position
from homcc.client.compilation import (  # pylint: disable=wrong-import-position
    DEFAULT_LOCALHOST,
    compile_locally,
    compile_remotely,
    scan_includes,
)
from homcc.client.parsing import (  # pylint: disable=wrong-import-position
    ClientConfig,
    Host,
    LogLevel,
    load_hosts,
    parse_cli_args,
    parse_config,
)
from homcc.common.arguments import Arguments  # pylint: disable=wrong-import-position
from homcc.common.errors import (  # pylint: disable=wrong-import-position
    HostParsingError,
    RecoverableClientError,
    RemoteCompilationError,
)
from homcc.common.logging import (  # pylint: disable=wrong-import-position
    Formatter,
    FormatterConfig,
    FormatterDestination,
    LoggingConfig,
    setup_logging,
)

logger: logging.Logger = logging.getLogger(__name__)

HOMCC_SAFEGUARD_ENV_VAR: str = "_HOMCC_SAFEGUARD"


def is_recursively_invoked() -> bool:
    """Check whether homcc was called recursively by checking the existence of a safeguard environment variable"""

    is_safeguard_active: bool = HOMCC_SAFEGUARD_ENV_VAR in os.environ
    os.environ[HOMCC_SAFEGUARD_ENV_VAR] = "1"  # activate safeguard
    return is_safeguard_active


def main():
    # cancel execution if recursive call is detected
    if is_recursively_invoked():
        print(f"{sys.argv[0]} seems to have been invoked recursively!", file=sys.stderr)
        sys.exit(os.EX_USAGE)

    # load and parse arguments and configuration information
    homcc_args_dict, compiler_or_argument, compiler_args = parse_cli_args(sys.argv[1:])

    # prevent config loading and parsing if --no-config was specified
    homcc_config: ClientConfig = ClientConfig.empty() if homcc_args_dict["no_config"] else parse_config()
    logging_config: LoggingConfig = LoggingConfig(
        config=FormatterConfig.COLORED,
        formatter=Formatter.CLIENT,
        destination=FormatterDestination.STREAM,
    )

    # LOG_LEVEL and VERBOSITY
    log_level: str = homcc_args_dict["log_level"]

    # verbosity implies debug mode
    if homcc_args_dict["verbose"] or homcc_config.verbose:
        logging_config.set_verbose()
        homcc_config.set_verbose()
    elif log_level == "DEBUG" or homcc_config.log_level == LogLevel.DEBUG:
        logging_config.set_debug()
        homcc_config.set_debug()

    # overwrite verbose debug logging level
    if log_level is not None:
        logging_config.level = LogLevel[log_level].value
        homcc_config.log_level = LogLevel[log_level]
    elif homcc_config.log_level is not None:
        logging_config.level = int(homcc_config.log_level)

    setup_logging(logging_config)

    compiler_arguments: Arguments = Arguments.from_cli(compiler_or_argument, compiler_args, homcc_config.compiler)
    # COMPILER; default: "cc"
    homcc_config.compiler = compiler_arguments.compiler

    # SCAN-INCLUDES; and exit
    if homcc_args_dict["scan_includes"]:
        for include in scan_includes(compiler_arguments):
            print(include)

        sys.exit(os.EX_OK)

    # HOST; get singular host from cli parameter or load hosts from $HOMCC_HOSTS env var or hosts file
    hosts: List[Host] = []
    hosts_file: Optional[str] = None
    localhost: Host = DEFAULT_LOCALHOST

    if (host_str := homcc_args_dict["host"]) is not None:
        hosts = [Host.from_str(host_str)]
    else:
        hosts_file, hosts_str = load_hosts()
        has_local: bool = False

        for host_str in hosts_str:
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

    # SCHROOT_PROFILE; DOCKER_CONTAINER; if --no-sandbox is specified do not use any specified sandbox configurations
    if homcc_args_dict["no_sandbox"]:
        homcc_config.schroot_profile = None
        homcc_config.docker_container = None
    else:
        if (schroot_profile := homcc_args_dict["schroot_profile"]) is not None:
            homcc_config.schroot_profile = schroot_profile

        if (docker_container := homcc_args_dict["docker_container"]) is not None:
            homcc_config.docker_container = docker_container

        if homcc_config.schroot_profile is not None and homcc_config.docker_container is not None:
            logger.error(
                "Can not specify a schroot profile and a docker container to be used simultaneously. "
                "Please specify only one of these config options."
            )
            sys.exit(os.EX_USAGE)

    # TIMEOUT
    if (timeout := homcc_args_dict["timeout"]) is not None:
        homcc_config.timeout = timeout

    # provide additional DEBUG information
    logger.debug(
        "%s - %s\n"  # homcc location and version
        "Caller:\t%s\n"  # homcc caller
        "%s"  # config info
        "Hosts (from [%s]):\n\t%s",  # hosts info
        sys.argv[0],
        client.__version__,
        sys.executable,
        homcc_config,
        hosts_file or f"--host={host_str}",
        "\n\t".join(str(host) for host in hosts),
    )

    # force local compilation on specific conditions
    if compiler_arguments.is_linking_only():
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
