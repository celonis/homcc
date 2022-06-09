"""Parsing related functionality regarding the homcc client"""
from __future__ import annotations

import logging
import os
import re
import sys

from abc import ABC, abstractmethod
from argparse import ArgumentParser, Action, RawTextHelpFormatter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from homcc.common.arguments import Arguments
from homcc.common.compression import Compression
from configparser import ConfigParser, SectionProxy
from homcc.common.logging import LogLevel
from homcc.common.parsing import default_locations, parse_configs
from homcc.client.errors import HostParsingError, NoHostsFoundError

logger = logging.getLogger(__name__)

HOMCC_HOSTS_ENV_VAR: str = "$HOMCC_HOSTS"
HOMCC_HOSTS_FILENAME: str = "hosts"
HOMCC_CLIENT_CONFIG_SECTION: str = "homcc"


class ConnectionType(str, Enum):
    """Helper class to distinguish between different host connection types"""

    LOCAL = "localhost"
    TCP = "TCP"
    SSH = "SSH"

    def is_local(self) -> bool:
        return self == ConnectionType.LOCAL


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

        super().__init__(nargs=nargs, help=kwargs.pop("help", self.__doc__), **kwargs)

    @abstractmethod
    def __call__(self, *_):
        pass


class ShowVersion(ShowAndExitAction):
    """show version and exit"""

    def __call__(self, *_):
        print("homcc 0.0.1")
        sys.exit(os.EX_OK)


class ShowHosts(ShowAndExitAction):
    """show host list and exit"""

    def __call__(self, *_):
        try:
            hosts: List[str] = load_hosts()

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
            hosts: List[str] = load_hosts()

        except NoHostsFoundError:
            print("Failed to get hosts list")
            sys.exit(os.EX_NOINPUT)

        concurrency_level: int = 0
        for host in hosts:
            concurrency_level += parse_host(host).limit or 0

        print(concurrency_level)
        sys.exit(os.EX_OK)


@dataclass
class Host:
    """Class to encapsulate host information"""

    type: ConnectionType
    host: str
    limit: int
    compression: Compression
    port: Optional[int]
    user: Optional[str]

    def __init__(
        self,
        *,
        type: ConnectionType,  # pylint: disable=redefined-builtin
        host: str,
        limit: Optional[str] = None,
        compression: Optional[str] = None,
        port: Optional[str] = None,
        user: Optional[str] = None,
    ):
        self.type = ConnectionType.LOCAL if host == ConnectionType.LOCAL else type
        self.host = host
        self.limit = int(limit) if limit is not None else 2  # enable minor level of concurrency on default
        self.compression = Compression.from_name(compression)
        self.port = int(port) if port is not None else None  # TCP
        self.user = user  # SSH


@dataclass
class ClientConfig:
    """Class to encapsulate and default client configuration information"""

    compiler: str
    compression: Compression
    profile: Optional[str]
    timeout: Optional[float]
    log_level: Optional[LogLevel]
    verbose: bool

    def __init__(
        self,
        *,
        compiler: Optional[str] = None,
        compression: Optional[str] = None,
        profile: Optional[str] = None,
        timeout: Optional[float] = None,
        log_level: Optional[str] = None,
        verbose: Optional[bool] = None,
    ):
        self.compiler = compiler or Arguments.DEFAULT_COMPILER
        self.compression = Compression.from_name(compression)
        self.profile = profile
        self.timeout = timeout
        self.log_level = LogLevel[log_level] if log_level else None
        self.verbose = verbose is not None and verbose

    @classmethod
    def from_config_section(cls, homcc_config: SectionProxy) -> ClientConfig:
        compiler: Optional[str] = homcc_config.get("compiler")
        compression: Optional[str] = homcc_config.get("compression")
        profile: Optional[str] = homcc_config.get("profile")
        timeout: Optional[float] = homcc_config.getfloat("timeout")
        log_level: Optional[str] = homcc_config.get("log_level")
        verbose: Optional[bool] = homcc_config.getboolean("verbose")

        return ClientConfig(
            compiler=compiler,
            compression=compression,
            profile=profile,
            timeout=timeout,
            log_level=log_level,
            verbose=verbose,
        )


def parse_cli_args(args: List[str]) -> Tuple[Dict[str, Any], Arguments]:
    parser: ArgumentParser = ArgumentParser(
        description="homcc - Home-Office friendly distcc replacement",
        allow_abbrev=False,
        add_help=False,
        formatter_class=RawTextHelpFormatter,
    )

    show_and_exit = parser.add_mutually_exclusive_group()
    show_and_exit.add_argument("--help", action="help", help="show this help message and exit")
    show_and_exit.add_argument("--version", action=ShowVersion)
    show_and_exit.add_argument("--show-hosts", action=ShowHosts)
    show_and_exit.add_argument("-j", action=ShowConcurrencyLevel)

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

    indented_newline: str = "\n\t"
    parser.add_argument(
        "--host",
        metavar="HOST",
        type=str,
        help="HOST defines the connection to the remote compilation server:\n"
        "\tHOST\t\tTCP connection to specified HOST with default port 3633\n"
        "\tHOST:PORT\tTCP connection to specified HOST with specified PORT\n"
        # TODO(s.pirsch): enable these lines once SSHClient is implemented, parsing should already work however
        # "\t@HOST\t\tSSH connection to specified HOST\n"
        # "\tUSER@HOST\tSSH connection to specified USER at HOST\n"
        "HOST,COMPRESSION defines any of the above HOST option and additionally specifies which "
        "COMPRESSION algorithm will be chosen\n\t"
        f"{indented_newline.join(Compression.descriptions())}",
    )

    profile = parser.add_mutually_exclusive_group()
    profile.add_argument(
        "--profile",
        type=str,
        help="PROFILE which will be mapped to predefined chroot environments on the selected remote compilation server,"
        " no profile is being used on default",
    )
    profile.add_argument(
        "--no-profile",
        action="store_true",
        help="enforce that no PROFILE is used even if one is specified in the configuration file",
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
        f'"{Arguments.DEFAULT_COMPILER}"\n'
        "dependant on remote execution, the remaining ARGUMENTS may be altered before being forwarded to the COMPILER",
    )

    # known args (used for homcc), unknown args (used as and forwarded to the compiler)
    homcc_args_namespace, compiler_args = parser.parse_known_args(args)
    homcc_args_dict = vars(homcc_args_namespace)

    compiler_or_argument: str = homcc_args_dict.pop("COMPILER_OR_ARGUMENT")  # either compiler or very first argument
    compiler_arguments: Arguments = Arguments.from_cli(compiler_or_argument, compiler_args)

    return homcc_args_dict, compiler_arguments


def parse_host(host: str) -> Host:
    """
    Try to categorize and extract the following information from the host in the general order of:
    - Compression
    - ConnectionType:
        - TCP:
            - HOST
            - [PORT]
        - SSH:
            - HOST
            - [USER]
    - Limit
    """
    # the following regexes are intentionally simple and contain a lot of false positives for IPv4 and IPv6 addresses,
    # matches are however merely used for rough categorization and don't test the validity of the actual host values,
    # since a single host line is usually short we parse over it multiple times for readability and maintainability,
    # meaningful failures on erroneous values will arise later on when the client tries to connect to the specified host

    host_dict: Dict[str, str] = {}
    connection_type: ConnectionType

    # trim trailing comment: HOST#COMMENT
    if (host_comment_match := re.match(r"^(\S+)#(\S+)$", host)) is not None:
        host, _ = host_comment_match.groups()

    # use trailing compression info: HOST,COMPRESSION
    if (host_compression_match := re.match(r"^(\S+),(\S+)$", host)) is not None:
        host, compression = host_compression_match.groups()
        host_dict["compression"] = compression

    # HOST:PORT/LIMIT
    if (host_port_limit_match := re.match(r"^(([\w./]+)|\[(\S+)]):(\d+)(/(\d+))?$", host)) is not None:
        _, name_or_ipv4, ipv6, port, _, limit = host_port_limit_match.groups()
        host = name_or_ipv4 or ipv6
        connection_type = ConnectionType.TCP
        host_dict["port"] = port
        host_dict["limit"] = limit
        return Host(type=connection_type, host=host, **host_dict)

    # USER@HOST
    elif (user_at_host_match := re.match(r"^(\w+)@([\w.:/]+)$", host)) is not None:
        user, host = user_at_host_match.groups()
        connection_type = ConnectionType.SSH
        host_dict["user"] = user

    # @HOST
    elif (at_host_match := re.match(r"^@([\w.:/]+)$", host)) is not None:
        host = at_host_match.group(1)
        connection_type = ConnectionType.SSH

    # HOST
    elif re.match(r"^([\w.:/]+)$", host) is not None:
        connection_type = ConnectionType.TCP

    else:
        raise HostParsingError(f'Host "{host}" could not be parsed correctly, please provide it in the correct format!')

    # extract remaining limit info: HOST_FORMAT/LIMIT
    if (host_limit_match := re.match(r"^(\S+)/(\d+)$", host)) is not None:
        host, limit = host_limit_match.groups()
        host_dict["limit"] = limit

    return Host(type=connection_type, host=host, **host_dict)


def load_hosts(hosts_file_locations: Optional[List[Path]] = None) -> List[str]:
    """
    Load homcc hosts from one of the following options:
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
        return filtered_lines(homcc_hosts_env_var)

    # HOSTS Files
    if not hosts_file_locations:
        hosts_file_locations = default_locations()

    for hosts_file_location in hosts_file_locations:
        if hosts_file_location.exists():
            if hosts_file_location.stat().st_size == 0:
                logger.warning('Skipping empty hosts file "%s"!', hosts_file_location)
                continue
            return filtered_lines(hosts_file_location.read_text(encoding="utf-8"))

    raise NoHostsFoundError("No hosts information were found!")


def parse_config(filenames: List[Path] = None) -> ClientConfig:
    cfg: ConfigParser = parse_configs(filenames or default_locations())

    if HOMCC_CLIENT_CONFIG_SECTION not in cfg.sections():
        return ClientConfig()

    return ClientConfig.from_config_section(cfg[HOMCC_CLIENT_CONFIG_SECTION])
