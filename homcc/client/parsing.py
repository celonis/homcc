"""Parsing related functionality regarding the homcc client"""
import logging
import os
import re
import sys

from abc import ABC, abstractmethod
from argparse import ArgumentParser, Action, Namespace, RawTextHelpFormatter
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from homcc.common.arguments import Arguments

logger = logging.getLogger(__name__)

HOMCC_HOSTS_ENV_VAR = "$HOMCC_HOSTS"
HOMCC_DIR_ENV_VAR = "$HOMCC_DIR"


class NoHostsFound(Exception):
    """
    Error class to indicate a recoverable error when hosts could neither be determined from the environment variable nor
    from the default hosts file locations
    """


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

        # use class docstring as help description if none is provided
        help_: str = kwargs.pop("help", self.__doc__)

        super().__init__(nargs=nargs, help=help_, **kwargs)

    @abstractmethod
    def __call__(
        self,
        parser: ArgumentParser,
        namespace: Namespace,
        values: Union[str, Sequence[Any], None],
        option_string: Optional[str] = None,
    ):
        pass


class ShowVersion(ShowAndExitAction):
    """show version and exit"""

    def __call__(self, *_):
        print("homcc 0.0.1")
        sys.exit(os.EX_OK)


class ShowHosts(ShowAndExitAction):
    """show host list and exit"""

    def __call__(self, *_):
        print("localhost/12")
        sys.exit(os.EX_OK)


class ShowConcurrencyLevel(ShowAndExitAction):
    """show the concurrency level, as calculated from the host list, and exit"""

    def __call__(self, *_):
        print("12")
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
    show_and_exit.add_argument("--hosts", "--show-hosts", action=ShowHosts)
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

    # TODO(s.pirsch): investigate this functionality in distcc
    # parser.add_argument("--randomize", action="store_true", help="randomize the server list before execution")

    parser.add_argument(
        "--host",
        metavar="HOST",
        type=str,
        help="HOST defines the connection to the remote compilation server:\n"
        "\tHOST\t\tTCP connection to specified HOST with PORT either from config file or default port 3633\n"
        "\tHOST:PORT\tTCP connection to specified HOST with specified PORT\n"
        # TODO(s.pirsch): enable these lines when SSHClient is implemented, parsing should already work
        # "\t@HOST\t\tSSH connection to specified HOST\n"
        # "\tUSER@HOST\tSSH connection to specified USER at HOST\n"
        "HOST,COMPRESSION defines any of the above HOST option and additionally specifies which "
        "COMPRESSION algorithm will be chosen\n"
        "\tlzo: Lempel–Ziv–Oberhumer compression",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        help="TIMEOUT in seconds to wait for a response from the remote compilation server",
    )

    # capturing all remaining arguments which represent compiler arguments via nargs=argparse.REMAINDER and
    # argparse.parse_args() is sadly not working as intended here, so we use the dummy "COMPILER_OR_ARGUMENT" argument
    # for the automatically generated usage string instead and handle the remaining, unknown arguments separately
    parser.add_argument(
        "COMPILER_OR_ARGUMENT",
        type=str,
        metavar="[COMPILER] ARGUMENTS ...",
        help=f"COMPILER, if not specified explicitly, is either read from the config file or defaults to "
        f'"{Arguments.default_compiler}"\n'
        f"all remaining ARGUMENTS will be directly forwarded to the COMPILER",
    )

    # known args (used for homcc), unknown args (forwarded to compiler)
    homcc_args_namespace, compiler_args = parser.parse_known_args(args)
    homcc_args_dict = vars(homcc_args_namespace)

    compiler_or_argument: str = homcc_args_dict.pop("COMPILER_OR_ARGUMENT")  # either compiler or very first argument
    compiler_arguments: Arguments = Arguments.from_cli(compiler_or_argument, compiler_args)

    return homcc_args_dict, compiler_arguments


class ConnectionType(str, Enum):
    """Helper class to distinguish between different host connection types"""

    TCP = "TCP"
    SSH = "SSH"


def parse_host(host: str) -> Dict[str, str]:
    # the following regexes are intentional simple and contain a lot of false positives for IPv4 and IPv6 addresses,
    # matches are however merely used for rough categorization and don't test the validity of the actual host values,
    # meaningful failures on erroneous values will arise later on when the client tries to connect to the specified host

    host_dict: Dict[str, str] = {}

    # HOST,COMPRESSION
    match: Optional[re.Match] = re.match(r"^(\S+),(\S+)$", host)

    if match:
        host, compression = match.groups()
        host_dict["compression"] = compression

    # USER@HOST
    match = re.match(r"^(\w+)@([\w.:]+)$", host)

    if match:
        user, host = match.groups()
        host_dict["type"] = ConnectionType.SSH
        host_dict["user"] = user
        host_dict["host"] = host
        return host_dict

    # @HOST
    match = re.match(r"^@([\w.:]+)$", host)

    if match:
        host_dict["type"] = ConnectionType.SSH
        host = match.group(1)
        host_dict["host"] = host
        return host_dict

    # HOST:PORT
    match = re.match(r"^(([\w.]+)|\[(\S+)]):(\d+)$", host)

    if match:
        host_dict["type"] = ConnectionType.TCP
        _, name_or_ipv4, ipv6, port = match.groups()
        host_dict["host"] = name_or_ipv4 or ipv6
        host_dict["port"] = port
        return host_dict

    # HOST
    match = re.match(r"^([\w.:]+)$", host)

    if match:
        host_dict["type"] = ConnectionType.TCP
        host_dict["host"] = host
        return host_dict

    raise ValueError(f'Host "{host}" could not be parsed correctly, please provide it in the correct format!')


def default_hosts_file_locations() -> List[Path]:
    """
    Default locations for the hosts file:
    - File: $HOMCC_DIR/hosts
    - File: ~/.homcc/hosts
    - File: /etc/homcc/hosts
    """

    # HOSTS file locations
    hosts_file_name: str = "hosts"
    homcc_dir_env_var = os.getenv(HOMCC_DIR_ENV_VAR)
    home_dir_homcc_hosts = Path("~/.homcc") / hosts_file_name
    etc_dir_homcc_hosts = Path("/etc/homcc") / hosts_file_name

    hosts_file_locations: List[Path] = []

    # $HOMCC_DIR/hosts
    if homcc_dir_env_var:
        homcc_dir_hosts = Path(homcc_dir_env_var) / hosts_file_name
        hosts_file_locations.append(homcc_dir_hosts)

    # ~/.homcc/hosts
    if home_dir_homcc_hosts.exists():
        hosts_file_locations.append(home_dir_homcc_hosts)

    # /etc/homcc/hosts
    if etc_dir_homcc_hosts.exists():
        hosts_file_locations.append(etc_dir_homcc_hosts)

    return hosts_file_locations


def load_hosts(hosts_file_locations: Optional[List[Path]] = None) -> List[str]:
    """
    Load homcc hosts from one of the following options:
    - Environment Variable: $HOMCC_HOSTS
    - Hosts file defined in hosts_locations parameter
    """

    def filter_and_rstrip_whitespace(data: str) -> List[str]:
        return [line.rstrip() for line in data.splitlines() if not line.isspace()]

    # $HOMCC_HOSTS
    homcc_hosts_env_var = os.getenv(HOMCC_HOSTS_ENV_VAR)
    if homcc_hosts_env_var:
        return filter_and_rstrip_whitespace(homcc_hosts_env_var)

    # hosts_file_locations parameter
    if hosts_file_locations and len(hosts_file_locations) == 0:
        raise NoHostsFound

    if not hosts_file_locations:
        hosts_file_locations = default_hosts_file_locations()

    for hosts_file_location in hosts_file_locations:
        if hosts_file_location.exists():
            if hosts_file_location.stat().st_size == 0:
                logger.warning('Hosts file "%s" appears to be empty.', hosts_file_location)
            return filter_and_rstrip_whitespace(hosts_file_location.read_text(encoding="utf-8"))

    raise NoHostsFound


def parse_config(config: str) -> Dict:
    config_info: List[str] = ["COMPILER", "DEBUG", "TIMEOUT", "COMPRESSION"]
    # TODO: capture trailing comments as third group?
    config_pattern: str = f"^({'|'.join(config_info)})=(\\S+)$"
    parsed_config = {}

    for line in config.splitlines():
        # remove leading and trailing whitespace as well as in-between space chars
        config_line = line.strip().replace(" ", "")

        # ignore comment lines
        if config_line.startswith("#"):
            continue

        # remove trailing comment
        match: Optional[re.Match] = re.match(r"^(\S+)#(\S+)$", config_line)
        if match:
            config_line, _ = match.groups()

        # parse and save config
        match = re.match(config_pattern, config_line, re.IGNORECASE)
        if match:
            key, value = match.groups()
            parsed_config[key.upper()] = value.lower()
        else:
            logger.warning(
                'Config line "%s" ignored\n'
                "To disable this warning, please correct or comment out the corresponding line!",
                line,
            )

    return parsed_config


def load_config_file() -> Dict:
    """
    Load homcc config from one of the following locations:
    - File: $HOMCC_DIR/config
    - File: ~/.homcc/config
    - File: ~/config/homcc/config
    - File: /etc/homcc/config
    """

    # config file locations
    config_file_name: str = "config"
    homcc_dir_env_var = os.getenv(HOMCC_DIR_ENV_VAR)
    home_dir_homcc_config = Path("~/.homcc") / config_file_name
    home_config_dir_homcc_config = Path("~/config/homcc") / config_file_name
    etc_dir_homcc_config = Path("/etc/homcc") / config_file_name

    config_file_path: Optional[Path] = None

    if homcc_dir_env_var:
        homcc_dir_config = Path(homcc_dir_env_var) / config_file_name
        if homcc_dir_config.exists():  # $HOMCC_DIR/config
            config_file_path = homcc_dir_config
    elif home_dir_homcc_config.exists():  # ~/.homcc/config
        config_file_path = home_dir_homcc_config
    elif home_config_dir_homcc_config.exists():  # ~/config/homcc/config
        config_file_path = home_config_dir_homcc_config
    elif etc_dir_homcc_config.exists():  # /etc/homcc/config
        config_file_path = etc_dir_homcc_config

    if config_file_path:
        if config_file_path.stat().st_size == 0:
            logger.info('Config file "%s" appears to be empty.', config_file_path)
        return parse_config(config_file_path.read_text(encoding="utf-8"))

    return {}
