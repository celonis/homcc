"""Parsing related functionality regarding the homcc client"""
from __future__ import annotations

import logging
import os
import sys
from abc import ABC, abstractmethod
from argparse import Action, ArgumentParser, RawTextHelpFormatter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from homcc import client
from homcc.client.compilation import scan_includes
from homcc.client.config import ClientConfig, parse_config
from homcc.client.host import Host
from homcc.common.arguments import Arguments
from homcc.common.compression import Compression
from homcc.common.errors import HostParsingError, NoHostsFoundError
from homcc.common.logging import (
    Formatter,
    FormatterConfig,
    FormatterDestination,
    LoggingConfig,
    LogLevel,
    setup_logging,
)
from homcc.common.parsing import default_locations

logger = logging.getLogger(__name__)

HOMCC_HOSTS_ENV_VAR: str = "HOMCC_HOSTS"
HOMCC_HOSTS_FILENAME: str = "hosts"


class ShowAndExitAction(ABC, Action):
    """
    Abstract base class to ensure correct initialization of flag arguments that have the behavior of "show and exit"
    and enable automatic help documentation for the CLI
    """

    def __init__(self, **kwargs):
        # ensure that the argument acts as a flag
        nargs: int = kwargs.pop("nargs", 0)

        if nargs != 0:
            raise ValueError(f"nargs is {nargs}, but {self.__class__.__name__} requires nargs to be 0")

        super().__init__(nargs=0, help=kwargs.pop("help", self.__doc__), **kwargs)

    @abstractmethod
    def __call__(self, *_):
        pass


class ShowHosts(ShowAndExitAction):
    """show host list and exit"""

    def __call__(self, *_):
        try:
            _, hosts = load_hosts()

        except NoHostsFoundError:
            print("Failed to get hosts list")
            sys.exit(os.EX_NOINPUT)

        for host in hosts:
            print(host)

        sys.exit(os.EX_OK)


class ShowConcurrencyLevel(ShowAndExitAction):
    """show the concurrency level, as calculated from the hosts list, and exit"""

    def __call__(self, *_):
        try:
            _, hosts = load_hosts()

        except NoHostsFoundError:
            print("Failed to get hosts list")
            sys.exit(os.EX_NOINPUT)

        concurrency_level: int = 0
        for host in hosts:
            concurrency_level += Host.from_str(host).limit or 0

        print(concurrency_level)
        sys.exit(os.EX_OK)


class ShowEnvironmentVariables(ShowAndExitAction):
    """show all utilized environmental variables with their set values and exit"""

    def __call__(self, *_):
        if (homcc_hosts_env_var := os.getenv(HOMCC_HOSTS_ENV_VAR)) is not None:
            print(f"{HOMCC_HOSTS_ENV_VAR}: {homcc_hosts_env_var}")

        for config_env_var in iter(ClientConfig.EnvironmentVariables):
            if (config := os.getenv(config_env_var)) is not None:
                print(f"{config_env_var}: {config}")

        sys.exit(os.EX_OK)


def parse_cli_args(args: List[str]) -> Tuple[Dict[str, Any], str, List[str]]:
    parser: ArgumentParser = ArgumentParser(
        description="homcc - Home-Office friendly distcc replacement",
        allow_abbrev=False,
        add_help=False,  # no default help argument in order to disable "-h" abbreviation
        formatter_class=RawTextHelpFormatter,
    )

    show_and_exit = parser.add_mutually_exclusive_group()
    show_and_exit.add_argument("--help", action="help", help="show this help message and exit")
    show_and_exit.add_argument("--version", action="version", version=f"homcc {client.__version__}")
    show_and_exit.add_argument("--show-hosts", action=ShowHosts)
    show_and_exit.add_argument("-j", "--show-concurrency", action=ShowConcurrencyLevel)
    show_and_exit.add_argument("--show-variables", action=ShowEnvironmentVariables)
    show_and_exit.add_argument(
        "--show-info",
        action="store_true",
        # nargs=0,
        help="show all relevant info regarding configuration and execution of homcc, and exit",
    )

    parser.add_argument(
        "--scan-includes",
        action="store_true",
        help="show all header dependencies that would be sent to the server, as calculated from the given arguments, "
        "and exit",
    )

    parser.add_argument(
        "--no-config",
        action="store_true",
        help="enforce that only configurations provided via the CLI are used",
    )

    parser.add_argument(
        "--log-level",
        required=False,
        type=str,
        choices=[level.name for level in LogLevel],
        help=f"set detail level for log messages, defaults to {LogLevel.INFO.name}",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="enable a verbose mode which implies detailed and colored logging of debug messages",
    )

    indented_newline: str = "\n\t"
    parser.add_argument(
        "--host",
        metavar="HOST",
        type=str,
        help="HOST defines the connection to the remote compilation server:\n"
        "\tHOST\t\tTCP connection to specified HOST with default port 3126\n"
        "\tHOST:PORT\tTCP connection to specified HOST with specified PORT\n"
        # TODO(s.pirsch): enable these lines once SSHClient is implemented, parsing should already work however
        # "\t@HOST\t\tSSH connection to specified HOST\n"
        # "\tUSER@HOST\tSSH connection to specified USER at HOST\n"
        "HOST,COMPRESSION defines any of the above HOST option and additionally specifies which "
        "COMPRESSION algorithm will be chosen\n\t"
        f"{indented_newline.join(Compression.descriptions())}",
    )

    sandbox_execution = parser.add_mutually_exclusive_group()
    sandbox_execution.add_argument(
        "--schroot-profile",
        type=str,
        help="SCHROOT_PROFILE which will be mapped to predefined chroot environments on "
        "the selected remote compilation server, no schroot profile is being used on default",
    )
    sandbox_execution.add_argument(
        "--docker-container",
        type=str,
        help="DOCKER_CONTAINER name which will be used to compile in on the selected remote compilation server,"
        " no docker container is being used on default",
    )
    sandbox_execution.add_argument(
        "--no-sandbox",
        action="store_true",
        help="enforce that no sandboxed execution is performed even if it is specified in the configuration file",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        help="TIMEOUT in seconds to wait for a response from the remote compilation server",
    )

    # capturing all remaining (compiler) arguments via nargs=argparse.REMAINDER and argparse.parse_args() is sadly not
    # working as intended, so we use the dummy "COMPILER_OR_ARGUMENT" argument for the automatically generated user-
    # facing strings instead and handle the remaining, unknown arguments separately
    parser.add_argument(
        "COMPILER_OR_ARGUMENT",
        type=str,
        metavar="[COMPILER] ARGUMENTS ...",
        help="COMPILER, if not specified explicitly, is either read from the config file or defaults to "
        f"'{Arguments.DEFAULT_COMPILER}'\n"
        "dependant on remote execution, the remaining ARGUMENTS may be altered before being forwarded to the COMPILER",
    )

    # known args (used for homcc), unknown args (used as and forwarded to the compiler)
    homcc_args_namespace, compiler_args = parser.parse_known_args(args)
    homcc_args_dict = vars(homcc_args_namespace)

    compiler_or_argument: str = homcc_args_dict.pop("COMPILER_OR_ARGUMENT")  # either compiler or very first argument

    return homcc_args_dict, compiler_or_argument, compiler_args


def setup_client(cli_args: List[str]) -> Tuple[ClientConfig, Arguments, List[Host]]:
    # load and parse arguments and configuration information
    homcc_args_dict, compiler_or_argument, compiler_args = parse_cli_args(cli_args[1:])

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
    # COMPILER; default: "gcc"
    homcc_config.compiler = compiler_arguments.compiler

    # SCAN-INCLUDES; and exit
    if homcc_args_dict["scan_includes"]:
        for include in scan_includes(compiler_arguments):
            print(include)

        sys.exit(os.EX_OK)

    # HOST; get singular host from cli parameter or load hosts from $HOMCC_HOSTS env var or hosts file
    hosts: List[Host] = []
    hosts_file: Optional[str] = None
    localhost: Host = Host.default_localhost()

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

    # SHOW-INFO; and exit
    if homcc_args_dict["show_info"]:
        print(
            f"homcc {client.__version__}"  # homcc version
            f"{sys.argv[0]} - {client.__version__}\n"  # homcc location and version
            f"Caller:\t{sys.executable}\n"  # homcc caller
            f"{homcc_config}"  # config info
            "Hosts (from [%s]):\n\t%s",  # hosts info
            hosts_file or f"--host={host_str}",
            "\n\t".join(str(host) for host in hosts),
        )

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

    return homcc_config, compiler_arguments, hosts


def load_hosts(hosts_file_locations: Optional[List[Path]] = None) -> Tuple[str, List[str]]:
    """
    Get homcc hosts by returning the source and unparsed strings from one of the following options:
    - Environment Variable: $HOMCC_HOSTS
    - Hosts files defined via parameter hosts_file_locations
    - Hosts files defined at default hosts file locations
    """

    def filtered_lines(text: str) -> List[str]:
        lines: List[str] = []

        for line in text.splitlines():
            # remove whitespace
            line = line.strip().replace(" ", "")

            # filter empty lines and comment lines
            if line and not line.startswith("#"):
                lines.append(line)

        return lines

    # $HOMCC_HOSTS
    homcc_hosts_env_var = os.getenv(HOMCC_HOSTS_ENV_VAR)
    if homcc_hosts_env_var:
        return HOMCC_HOSTS_ENV_VAR, filtered_lines(homcc_hosts_env_var)

    # HOSTS Files
    if not hosts_file_locations:
        hosts_file_locations = default_locations(HOMCC_HOSTS_FILENAME)

    for hosts_file_location in hosts_file_locations:
        if hosts_file_location.exists():
            if hosts_file_location.stat().st_size == 0:
                logger.warning("Skipping empty hosts file '%s'!", hosts_file_location)
                continue
            return str(hosts_file_location), filtered_lines(hosts_file_location.read_text(encoding="utf-8"))

    raise NoHostsFoundError("No hosts information were found!")
