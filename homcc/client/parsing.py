"""Parsing related functionality regarding the homcc client"""
import logging
import os
import re
import sys

from abc import ABC, abstractmethod
from argparse import ArgumentParser, Action, RawTextHelpFormatter
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from homcc.common.arguments import Arguments
from homcc.common.compression import Compression
from homcc.common.parsing import parse_config_keys, load_config_file_from

logger = logging.getLogger(__name__)

HOMCC_HOSTS_ENV_VAR = "$HOMCC_HOSTS"
HOMCC_DIR_ENV_VAR = "$HOMCC_DIR"


class NoHostsFoundError(Exception):
    """
    Error class to indicate a recoverable error when hosts could neither be determined from the environment variable nor
    from the default hosts file locations
    """


class ConnectionType(str, Enum):
    """Helper class to distinguish between different host connection types"""

    TCP = "TCP"
    SSH = "SSH"


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
            concurrency_level += int(parse_host(host).get("limit", 0))

        print(concurrency_level)
        sys.exit(os.EX_OK)


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
        "--DEBUG",
        action="store_true",
        help="enables a verbose DEBUG mode which prints detailed, colored logging messages to the terminal",
    )

    parser.add_argument(
        "--scan-includes",
        action="store_true",
        help="show all dependencies that would be sent to the server, as calculated from the given arguments, and exit",
    )

    indented_newline: str = "\n\t"
    parser.add_argument(
        "--host",
        metavar="HOST",
        type=str,
        help="HOST defines the connection to the remote compilation server:\n"
        "\tHOST\t\tTCP connection to specified HOST with PORT either from config file or default port 3633\n"
        "\tHOST:PORT\tTCP connection to specified HOST with specified PORT\n"
        # TODO(s.pirsch): enable these lines once SSHClient is implemented, parsing should already work however
        # "\t@HOST\t\tSSH connection to specified HOST\n"
        # "\tUSER@HOST\tSSH connection to specified USER at HOST\n"
        "HOST,COMPRESSION defines any of the above HOST option and additionally specifies which "
        "COMPRESSION algorithm will be chosen\n\t"
        f"{indented_newline.join(Compression.descriptions())}",
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
        f'"{Arguments.default_compiler}"\n'
        "all remaining ARGUMENTS will be directly forwarded to the COMPILER",
    )

    # known args (used for homcc), unknown args (used as and forwarded to the compiler)
    homcc_args_namespace, compiler_args = parser.parse_known_args(args)
    homcc_args_dict = vars(homcc_args_namespace)

    compiler_or_argument: str = homcc_args_dict.pop("COMPILER_OR_ARGUMENT")  # either compiler or very first argument
    compiler_arguments: Arguments = Arguments.from_cli(compiler_or_argument, compiler_args)

    return homcc_args_dict, compiler_arguments


def parse_host(host: str) -> Dict[str, str]:
    """
    try to categorize and extract the following information from the host:
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

    # trim trailing comment
    host_comment_match = re.match(r"^(\S+)#(\S+)$", host)  # HOST#COMMENT

    if host_comment_match:  # HOST#COMMENT
        host, _ = host_comment_match.groups()

    # use trailing compression info
    host_compression_match = re.match(r"^(\S+),(\S+)$", host)  # HOST,COMPRESSION

    if host_compression_match:  # HOST,COMPRESSION
        host, compression = host_compression_match.groups()

        if Compression.get(compression):
            host_dict["compression"] = compression
        else:
            logger.error(
                'Compression "%s" is currently not supported! '
                "The remote compilation will be executed without compression enabled!",
                compression,
            )

    # categorize host format
    user_at_host_match = re.match(r"^(\w+)@([\w.:/]+)$", host)  # USER@HOST
    at_host_match = re.match(r"^@([\w.:/]+)$", host)  # @HOST
    host_port_limit_match = re.match(r"^(([\w./]+)|\[(\S+)]):(\d+)(/(\d+))?$", host)  # HOST:PORT/LIMIT
    host_match = re.match(r"^([\w.:/]+)$", host)  # HOST

    if user_at_host_match:  # USER@HOST
        user, host = user_at_host_match.groups()
        host_dict["type"] = ConnectionType.SSH
        host_dict["user"] = user

    elif at_host_match:  # @HOST
        host = at_host_match.group(1)
        host_dict["type"] = ConnectionType.SSH

    elif host_port_limit_match:  # HOST:PORT
        _, name_or_ipv4, ipv6, port, _, limit = host_port_limit_match.groups()
        host = name_or_ipv4 or ipv6
        host_dict["type"] = ConnectionType.TCP
        host_dict["port"] = port
        host_dict["limit"] = limit
        host_dict["host"] = host
        return host_dict

    elif host_match:  # HOST
        host_dict["type"] = ConnectionType.TCP

    else:
        raise ValueError(f'Host "{host}" could not be parsed correctly, please provide it in the correct format!')

    # extract remaining limit info
    host_limit_match = re.match(r"^(\S+)/(\d+)$", host)  # HOST/LIMIT

    if host_limit_match:  # HOST/LIMIT
        host, limit = host_limit_match.groups()
        host_dict["limit"] = limit

    host_dict["host"] = host

    return host_dict


def default_hosts_file_locations() -> List[Path]:
    """
    Default locations for the hosts file:
    - File: $HOMCC_DIR/hosts
    - File: ~/.homcc/hosts
    - File: ~/.config/homcc/hosts
    - File: /etc/homcc/hosts
    """

    # HOSTS file locations
    hosts_file_name: str = "hosts"
    homcc_dir_env_var = os.getenv(HOMCC_DIR_ENV_VAR)
    home_dir_homcc_hosts = Path.home() / ".homcc" / hosts_file_name
    home_dir_config_homcc_hosts = Path.home() / ".config/homcc" / hosts_file_name
    etc_dir_homcc_hosts = Path("/etc/homcc") / hosts_file_name

    hosts_file_locations: List[Path] = []

    # $HOMCC_DIR/hosts
    if homcc_dir_env_var:
        homcc_dir_hosts = Path(homcc_dir_env_var) / hosts_file_name
        hosts_file_locations.append(homcc_dir_hosts)

    # ~/.homcc/hosts
    if home_dir_homcc_hosts.exists():
        hosts_file_locations.append(home_dir_homcc_hosts)

    # ~/.config/homcc/hosts
    if home_dir_config_homcc_hosts.exists():
        hosts_file_locations.append(home_dir_config_homcc_hosts)

    # /etc/homcc/hosts
    if etc_dir_homcc_hosts.exists():
        hosts_file_locations.append(etc_dir_homcc_hosts)

    return hosts_file_locations


def load_hosts(hosts_file_locations: Optional[List[Path]] = None) -> List[str]:
    """
    Load homcc hosts from one of the following options:
    - Environment Variable: $HOMCC_HOSTS
    - Hosts files defined at default hosts file locations
    """

    def filtered_lines(text: str) -> List[str]:
        lines: List[str] = []

        for line in text.splitlines():
            # remove whitespace
            line = line.strip().replace(" ", "")

            # filter empty lines and comment lines
            if len(line) != 0 and not line.startswith("#"):
                lines.append(line)

        return lines

    # $HOMCC_HOSTS
    homcc_hosts_env_var = os.getenv(HOMCC_HOSTS_ENV_VAR)
    if homcc_hosts_env_var:
        return filtered_lines(homcc_hosts_env_var)

    # HOSTS Files
    if hosts_file_locations and len(hosts_file_locations) == 0:
        raise NoHostsFoundError

    if not hosts_file_locations:
        hosts_file_locations = default_hosts_file_locations()

    for hosts_file_location in hosts_file_locations:
        if hosts_file_location.exists():
            if hosts_file_location.stat().st_size == 0:
                logger.warning('Skipping empty hosts file "%s"!', hosts_file_location)
                continue
            return filtered_lines(hosts_file_location.read_text(encoding="utf-8"))

    raise NoHostsFoundError


def parse_config(config_lines: List[str]) -> Dict[str, str]:
    config_keys: List[str] = ["compiler", "compression", "debug", "timeout"]
    return parse_config_keys(config_keys, config_lines)


def load_config_file(config_file_locations: Optional[List[Path]] = None) -> List[str]:
    """load a homcc config file from the default locations are as parameterized by config_file_locations"""

    if not config_file_locations:
        return load_config_file_from(default_config_file_locations())

    return load_config_file_from(config_file_locations)


def default_config_file_locations() -> List[Path]:
    """
    Load homcc config from one of the following locations:
    - File: $HOMCC_DIR/client.conf
    - File: ~/.homcc/client.conf
    - File: ~/.config/homcc/client.conf
    - File: /etc/homcc/client.conf
    """

    # config file locations
    config_file_name: str = "client.conf"
    homcc_dir_env_var = os.getenv(HOMCC_DIR_ENV_VAR)
    home_dir_homcc_config = Path.home() / ".homcc" / config_file_name
    home_config_dir_homcc_config = Path.home() / ".config/homcc" / config_file_name
    etc_dir_homcc_config = Path("/etc/homcc") / config_file_name

    config_file_locations: List[Path] = []

    # $HOMCC_DIR/client.conf
    if homcc_dir_env_var:
        homcc_dir_config = Path(homcc_dir_env_var) / config_file_name
        config_file_locations.append(homcc_dir_config)

    # ~/.homcc/client.conf
    if home_dir_homcc_config.exists():
        config_file_locations.append(home_dir_homcc_config)

    # ~/.config/homcc/client.conf
    if home_config_dir_homcc_config.exists():
        config_file_locations.append(home_config_dir_homcc_config)

    # /etc/homcc/client.conf
    if etc_dir_homcc_config.exists():
        config_file_locations.append(etc_dir_homcc_config)

    return config_file_locations
