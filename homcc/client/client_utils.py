"""
fundamental utility functions and Exception class for the homcc client to interact with the linux
command line and the specified compiler
"""
import logging
import os
import re
import subprocess
import sys

from abc import ABC, abstractmethod
from argparse import ArgumentParser, Action, Namespace, RawTextHelpFormatter
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Sequence, Tuple, Union

from homcc.common.arguments import Arguments, ArgumentsExecutionResult
from homcc.common.hashing import hash_file_with_path
from homcc.common.messages import ObjectFile

logger = logging.getLogger(__name__)

HOMCC_HOSTS_ENV_VAR = "$HOMCC_HOSTS"
HOMCC_DIR_ENV_VAR = "$HOMCC_DIR"


class CompilerError(subprocess.CalledProcessError):
    """
    Error class to indicate unrecoverability for the client main function and provide error information that occurred
    during execution of compiler commands
    """

    def __init__(self, err: subprocess.CalledProcessError):
        super().__init__(err.returncode, err.cmd, err.output, err.stderr)


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


def parse_args(args: List[str]) -> Tuple[Dict[str, Any], Arguments]:
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

    # parser.add_argument("--randomize", action="store_true", help="randomize the server list before execution")

    parser.add_argument(
        "--host",
        metavar="HOST",
        type=str,
        help="HOST defines the connection to the remote compilation server:\n"
        "\tHOST\t\tTCP connection to specified HOST with PORT either from config file or default port 3633\n"
        "\tHOST:PORT\tTCP connection to specified HOST with specified PORT\n"
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
    compiler_arguments: Arguments = Arguments.from_args(compiler_or_argument, compiler_args)

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


def scan_includes(arguments: Arguments) -> int:
    try:
        dependencies = find_dependencies(arguments)
    except CompilerError as err:
        return err.returncode

    source_files: List[str] = arguments.source_files

    for dependency in dependencies:
        if dependency not in source_files:
            print(dependency)

    return os.EX_OK


def load_hosts() -> List[str]:
    """
    Load homcc hosts from one of the following locations:
    - Environment Variable: $HOMCC_HOSTS
    - File: $HOMCC_DIR/hosts
    - File: ~/.homcc/hosts
    - File: /etc/homcc/hosts
    """

    def filter_and_rstrip_whitespace(data: str) -> List[str]:
        return [line.rstrip() for line in data.splitlines() if not line.isspace()]

    # $HOMCC_HOSTS
    homcc_hosts_env_var = os.getenv(HOMCC_HOSTS_ENV_VAR)
    if homcc_hosts_env_var:
        return filter_and_rstrip_whitespace(homcc_hosts_env_var)

    # HOSTS File
    hosts_file_name: str = "hosts"
    homcc_dir_env_var = os.getenv(HOMCC_DIR_ENV_VAR)
    home_dir_homcc_hosts = Path("~/.homcc") / hosts_file_name
    etc_dir_homcc_hosts = Path("/etc/homcc") / hosts_file_name

    hosts_file_path: Optional[Path] = None

    if homcc_dir_env_var:
        homcc_dir_hosts = Path(homcc_dir_env_var) / hosts_file_name
        if homcc_dir_hosts.exists():  # $HOMCC_DIR/hosts
            hosts_file_path = homcc_dir_hosts
    elif home_dir_homcc_hosts.exists():  # ~/.homcc/hosts
        hosts_file_path = home_dir_homcc_hosts
    elif etc_dir_homcc_hosts.exists():  # /etc/homcc/hosts
        hosts_file_path = etc_dir_homcc_hosts

    if hosts_file_path:
        if hosts_file_path.stat().st_size == 0:
            logger.warning('Hosts file "%s" appears to be empty.', hosts_file_path)
        return filter_and_rstrip_whitespace(hosts_file_path.read_text(encoding="utf-8"))

    # return empty list if no hosts information is available
    return []


def parse_config(config: str) -> Dict:
    config_info: List[str] = ["DEBUG", "TIMEOUT", "COMPRESSION"]
    # TODO: capture trailing comments as third group?
    config_pattern: str = f"^({'|'.join(config_info)})=(\\S+)$"
    parsed_config = {}

    for line in config.splitlines():
        # remove leading and trailing whitespace as well as in-between space chars
        stripped_line = line.strip().replace(" ", "")

        # ignore comment lines
        if stripped_line.startswith("#"):
            continue

        match = re.match(config_pattern, stripped_line, re.IGNORECASE)
        if match:
            key, value = match.groups()
            parsed_config[key.upper()] = value.lower()
        else:
            logger.warning(
                'Config line "%s" ignored\nTo disable this warning, please comment out the corresponding line!', line
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

    # Config File
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


def find_dependencies(arguments: Arguments) -> Set[str]:
    """get unique set of dependencies by calling the preprocessor and filtering the result"""
    try:
        # execute preprocessor command, e.g.: "g++ main.cpp -MM"
        result: ArgumentsExecutionResult = arguments.dependency_finding().execute(check=True)
    except subprocess.CalledProcessError as err:
        logger.error("Preprocessor error:\n%s", err.stderr)
        raise CompilerError(err) from err

    if result.stdout:
        logger.debug("Preprocessor result:\n%s", result.stdout)

    excluded_dependency_prefixes = ["/usr/include", "/usr/lib"]

    # create unique set of dependencies by filtering the preprocessor result
    def is_sendable_dependency(dependency: str) -> bool:
        if dependency in [f"{Arguments.preprocessor_target}:", "\\"]:
            return False

        for excluded_prefix in excluded_dependency_prefixes:
            if dependency.startswith(excluded_prefix):
                return False

        return True

    return set(filter(is_sendable_dependency, result.stdout.split()))


def calculate_dependency_dict(dependencies: Set[str]) -> Dict[str, str]:
    """calculate dependency file hashes mapped to their corresponding absolute filenames"""
    return {dependency: hash_file_with_path(dependency) for dependency in dependencies}


def invert_dict(to_invert: Dict):
    return {v: k for k, v in to_invert.items()}


def link_object_files(arguments: Arguments, object_files: List[ObjectFile]) -> int:
    """link all object files compiled by the server"""
    if len(arguments.source_files) != len(object_files):
        logger.error(
            "Wanted to build #%i source files, but only got #%i object files back from the server.",
            len(arguments.source_files),
            len(object_files),
        )

    arguments.remove_source_file_args()

    for object_file in object_files:
        arguments.add_arg(object_file.file_name)

    try:
        # execute linking command, e.g.: "g++ foo.o bar.o -ofoobar"
        result: ArgumentsExecutionResult = arguments.execute(check=True)
    except subprocess.CalledProcessError as err:
        logger.error("Linker error:\n%s", err.stderr)
        return err.returncode

    if result.stdout:
        logger.debug("Linker result:\n%s", result.stdout)

    return result.return_code


def compile_locally(arguments: Arguments) -> int:
    """execute local compilation"""
    logger.warning("Compiling locally instead!")
    try:
        # execute compile command, e.g.: "g++ foo.cpp -o foo"
        result: ArgumentsExecutionResult = arguments.execute(check=True)
    except subprocess.CalledProcessError as err:
        logger.error("Compiler error:\n%s", err.stderr)
        return err.returncode

    if result.stdout:
        logger.debug("Compiler result:\n%s", result.stdout)

    return result.return_code
