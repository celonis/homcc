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
from homcc.client.config import ClientConfig, ClientEnvironmentVariables, parse_config
from homcc.client.host import Host
from homcc.common.arguments import Arguments, Compiler
from homcc.common.compression import Compression
from homcc.common.constants import ENCODING
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


class ShowVersion(ShowAndExitAction):
    """show version and exit"""

    def __call__(self, *_):
        sys.stdout.write(f"homcc {client.__version__}\n")
        sys.exit(os.EX_OK)


class ShowHosts(ShowAndExitAction):
    """show host list and exit"""

    def __call__(self, *_):
        try:
            _, hosts = load_hosts()

        except NoHostsFoundError as error:
            sys.stderr.write(f"{error.message}\n")
            raise SystemExit(os.EX_NOINPUT) from error

        for host in hosts:
            sys.stdout.write(f"{host}\n")

        sys.exit(os.EX_OK)


class ShowConcurrencyLevel(ShowAndExitAction):
    """show the concurrency level, as calculated from the hosts list, and exit"""

    def __call__(self, *_):
        try:
            _, hosts = load_hosts()

        except NoHostsFoundError as error:
            sys.stderr.write("Failed to get hosts list\n")
            raise SystemExit(os.EX_NOINPUT) from error

        concurrency_level: int = 0
        for host in hosts:
            concurrency_level += Host.from_str(host).limit or 0

        sys.stdout.write(f"{concurrency_level}\n")
        sys.exit(os.EX_OK)


class ShowEnvironmentVariables(ShowAndExitAction):
    """show all utilized environmental variables with their set values and exit"""

    def __call__(self, *_):
        if (homcc_hosts_env_var := os.getenv(HOMCC_HOSTS_ENV_VAR)) is not None:
            sys.stdout.write(f"{HOMCC_HOSTS_ENV_VAR}: {homcc_hosts_env_var}\n")

        for config_env_var in iter(ClientEnvironmentVariables()):
            if (config := os.getenv(config_env_var)) is not None:
                sys.stdout.write(f"{config_env_var}: {config}\n")

        sys.exit(os.EX_OK)


def parse_cli_args(cli_args: List[str]) -> Tuple[Dict[str, Any], Arguments]:
    parser: ArgumentParser = ArgumentParser(
        description="homcc - Home-Office friendly distcc replacement",
        allow_abbrev=False,
        add_help=False,  # no default help argument in order to disable "-h" abbreviation
        formatter_class=RawTextHelpFormatter,
    )

    show_and_exit = parser.add_mutually_exclusive_group()
    show_and_exit.add_argument("--help", action="help", help="show this help message and exit")
    show_and_exit.add_argument("--version", action=ShowVersion)
    show_and_exit.add_argument("--show-hosts", action=ShowHosts)
    show_and_exit.add_argument("-j", "--show-concurrency", action=ShowConcurrencyLevel)
    show_and_exit.add_argument("--show-variables", action=ShowEnvironmentVariables)

    parser.add_argument(
        "--scan-includes",
        action="store_true",
        help="show all header dependencies that would be sent to the server, as calculated from the given arguments, "
        "and exit",
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

    parser.add_argument(
        "--no-config",
        action="store_true",
        help="enforce that only configurations provided via the CLI are used",
    )

    parser.add_argument(
        "--no-local-compilation",
        action="store_true",
        help="enforce that even on recoverable failures no local compilation is executed",
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
        "--compilation_request_timeout",
        metavar="TIMEOUT",
        type=float,
        help="TIMEOUT in seconds to wait for a response from the remote compilation server",
    )

    parser.add_argument(
        "--establish_connection_timeout",
        metavar="TIMEOUT",
        type=float,
        help="TIMEOUT in seconds for establishing a connection to a remote compilation server",
    )

    parser.add_argument(
        "--remote_compilation_tries",
        metavar="AMOUNT",
        type=int,
        help="maximal AMOUNT of remote compilation servers that are requested from for a single compilation",
    )

    # this argument will only be used to automatically generate user-facing strings
    parser.add_argument(
        "COMPILER_ARGUMENTS",
        type=str,
        metavar="COMPILER ARGUMENTS ...",
        help="COMPILER which should be used for local and remote compilation, dependant on the remote configuration, "
        "the COMPILER might be adapted to match the target architecture and the remaining ARGUMENTS may be altered "
        "before being forwarded to and executed by the actual COMPILER",
    )

    # split cli_args in order to respectively use them for homcc client or the specified compiler
    for i, arg in enumerate(cli_args[1:]):  # skip first arg since it's always homcc itself
        if Arguments.is_compiler_arg(arg):
            homcc_args_dict: Dict[str, Any] = vars(parser.parse_args(cli_args[: i + 1]))
            compiler_arguments: Arguments = Arguments(Compiler.from_str(arg), cli_args[i + 2 :])
            break
    else:
        # no compiler invocation, all cli_args are handled implicitly via argparse
        parser.parse_args(cli_args)
        sys.exit(os.EX_OK)

    # remove all args that are already implicitly handled via their actions or are compiler related
    for key in ("COMPILER_ARGUMENTS", "show_hosts", "show_concurrency", "show_variables", "version"):
        homcc_args_dict.pop(key)

    return homcc_args_dict, compiler_arguments


def setup_client(cli_args: List[str]) -> Tuple[ClientConfig, Arguments, Host, List[Host]]:
    homcc_args_dict: Dict[str, Any]
    compiler_arguments: Arguments

    # load and parse arguments and configuration information
    if Arguments.is_compiler_arg(cli_args[0]):  # e.g. when "g++" is symlinked to "homcc"
        normalized_compiler: Compiler = Compiler.from_str(cli_args[0]).normalized()
        homcc_args_dict, compiler_arguments = {}, Arguments(normalized_compiler, cli_args[1:])
    else:  # e.g. explicit "homcc ... g++ ..." call
        homcc_args_dict, compiler_arguments = parse_cli_args(cli_args)

    # prevent config loading and parsing if --no-config was specified
    homcc_config: ClientConfig = ClientConfig.empty() if homcc_args_dict.pop("no_config", False) else parse_config()
    logging_config: LoggingConfig = LoggingConfig(
        config=FormatterConfig.COLORED,
        formatter=Formatter.CLIENT,
        destination=FormatterDestination.STREAM,
        level=LogLevel.INFO,
    )

    # if the compiler output must be parsable we explicitly disable verbose logging and default to INFO logs
    if compiler_arguments.must_be_parsable():
        homcc_args_dict["verbose"] = False
        homcc_config.verbose = False
        homcc_args_dict["log_level"] = LogLevel.INFO.name
        homcc_config.log_level = LogLevel.INFO

    # LOG_LEVEL and VERBOSITY
    log_level: Optional[str] = homcc_args_dict.pop("log_level", None)

    # verbosity implies debug mode
    if homcc_args_dict.pop("verbose", False) or homcc_config.verbose:
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

    # SCAN-INCLUDES; and exit
    if homcc_args_dict.pop("scan_includes", False):
        for include in scan_includes(compiler_arguments):
            sys.stdout.write(f"{include}\n")

        sys.exit(os.EX_OK)

    # HOST; get singular host from cli parameter or load hosts from $HOMCC_HOSTS env var or hosts file
    remote_hosts: List[Host] = []
    hosts_file: Optional[str] = None

    # use the default localhost if no localhost is provided by the user explicitly
    # this dedicated host will limit the amount of locally running compilation jobs
    localhost: Host = Host.default_localhost()

    if (host_str := homcc_args_dict.pop("host", None)) is not None:
        remote_hosts = [Host.from_str(host_str)]
    else:
        try:
            hosts_file, hosts_str = load_hosts()
        except NoHostsFoundError as error:
            logger.error(error.message)
            raise SystemExit(os.EX_NOINPUT) from error

        has_local: bool = False

        for host_str in hosts_str:
            try:
                host: Host = Host.from_str(host_str)
            except HostParsingError as error:
                logger.warning("%s", error)
                continue

            if host.is_local():
                if has_local:
                    logger.warning("Multiple localhosts provided, using %s", localhost)

                has_local = True
                localhost = host
            else:
                remote_hosts.append(host)

    logger.debug(
        "%s - %s\n"  # homcc location and version
        "Caller:\t%s\n"  # homcc caller
        "%s"  # config info
        "Hosts ('%s'):\n\t%s",  # hosts info
        sys.argv[0],
        client.__version__,
        sys.executable,
        homcc_config,
        hosts_file or f"--host={host_str}",
        "\n\t".join(str(host) for host in [localhost] + remote_hosts),
    )

    # NO-LOCAL-COMPILATION
    if local_compilation_enabled := not homcc_args_dict.pop("no_local_compilation", False):
        homcc_config.local_compilation_enabled = local_compilation_enabled

    # SCHROOT_PROFILE; DOCKER_CONTAINER; if --no-sandbox is specified do not use any specified sandbox configurations
    if homcc_args_dict.pop("no_sandbox", False):
        homcc_args_dict.pop("schroot_profile")
        homcc_config.schroot_profile = None
        homcc_args_dict.pop("docker_container")
        homcc_config.docker_container = None
    else:
        if (schroot_profile := homcc_args_dict.pop("schroot_profile", None)) is not None:
            homcc_config.schroot_profile = schroot_profile

        if (docker_container := homcc_args_dict.pop("docker_container", None)) is not None:
            homcc_config.docker_container = docker_container

        if homcc_config.schroot_profile is not None and homcc_config.docker_container is not None:
            logger.error(
                "Can not specify a schroot profile and a docker container to be used simultaneously. "
                "Please specify only one of these config options."
            )
            sys.exit(os.EX_USAGE)

    # COMPILATION_REQUEST_TIMEOUT
    if (compilation_request_timeout := homcc_args_dict.pop("compilation_request_timeout", None)) is not None:
        homcc_config.compilation_request_timeout = compilation_request_timeout

    # ESTABLISH_CONNECTION_TIMEOUT
    if (establish_connection_timeout := homcc_args_dict.pop("establish_connection_timeout", None)) is not None:
        homcc_config.establish_connection_timeout = establish_connection_timeout

    # REMOTE_COMPILATION_TRIES
    if (remote_compilation_tries := homcc_args_dict.pop("remote_compilation_tries", None)) is not None:
        homcc_config.remote_compilation_tries = remote_compilation_tries

    # verify that all homcc cli args were handled
    if homcc_args_dict:
        logger.error("Unhandled arguments: %s", homcc_args_dict)
        sys.exit(os.EX_SOFTWARE)

    return homcc_config, compiler_arguments, localhost, remote_hosts


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
            return str(hosts_file_location), filtered_lines(hosts_file_location.read_text(encoding=ENCODING))

    raise NoHostsFoundError("No hosts information were found!")
