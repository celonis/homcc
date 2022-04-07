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
from typing import Any, Dict, List, Optional, Set, Sequence, Tuple, Union

from homcc.common.arguments import Arguments, ArgumentsExecutionResult
from homcc.common.hashing import hash_file_with_path
from homcc.common.messages import ObjectFile

logger = logging.getLogger(__name__)


class CompilerError(subprocess.CalledProcessError):
    """Error class to indicate unrecoverability for the client main function and provide error information that occurred
    during execution of compiler commands"""

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


class ShowDependencies(ShowAndExitAction):
    """show the dependencies that would be sent to the server, as calculated from the given arguments, and exit"""

    def __call__(self, parser: ArgumentParser, namespace: Namespace, values, option_string: Optional[str] = None):
        # this action requires unknown arguments (compiler arguments) and can not be accessed here
        # the functionality of this action is provided in show_dependencies and called by parse_and_handle_args
        namespace.dependencies = True


def parse_args(args: List[str]) -> Tuple[Dict[str, Any], Arguments]:
    parser: ArgumentParser = ArgumentParser(
        description="homcc - Home-Office friendly distcc replacement",
        allow_abbrev=False,
        add_help=False,
        formatter_class=RawTextHelpFormatter,
    )

    show_and_exit = parser.add_mutually_exclusive_group()
    show_and_exit.add_argument("--help", "-h", action="help", help="show this help message and exit")
    show_and_exit.add_argument("--version", action=ShowVersion)
    show_and_exit.add_argument("--hosts", "--show-hosts", action=ShowHosts)
    show_and_exit.add_argument("-j", action=ShowConcurrencyLevel)
    show_and_exit.add_argument("--dependencies", "--scan-includes", action=ShowDependencies)

    # subparsers = parser.add_subparsers()
    # subparsers.add_parser("COMPILER OPTIONS")

    # parser.add_argument("--randomize", action="store_true", help="randomize the server list before execution")

    parser.add_argument(
        "--dest",
        required=False,
        metavar="DESTINATION",
        type=str,
        help="DESTINATION defines the connection to the remote compilation server:\n"
        "\tHOST\t\tTCP connection to specified HOST with PORT either from config file or default port 3633\n"
        "\tHOST:PORT\tTCP connection to specified HOST with specified PORT\n"
        # "\t@HOST\t\tSSH connection to specified HOST\n"
        # "\tUSER@HOST\tSSH connection to specified USER at HOST\n"
        "DESTINATION,COMPRESSION defines any DESTINATION option from above with additional COMPRESSION information\n"
        "\tlzo: Lempel–Ziv–Oberhumer compression",
    )

    parser.add_argument(
        "--timeout",
        required=False,
        type=float,
        help="timeout in seconds to wait for a response from the remote compilation server",
    )

    parser.add_argument(
        "--DEBUG",
        required=False,
        action="store_true",
        help="enables the DEBUG mode which prints detailed, colored logging messages to the terminal",
    )

    # capturing all remaining arguments which represent compiler arguments via nargs=argparse.REMAINDER is sadly not
    # working as intended here, so we use the dummy "COMPILER_OR_ARGUMENT" argument for the automatically generated
    # usage string instead and handle the remaining, unknown arguments separately when accessing this argument
    parser.add_argument(
        "COMPILER_OR_ARGUMENT",
        type=str,
        metavar="[COMPILER] ARGUMENTS",
        help=f"COMPILER, if not specified explicitly, is either read from the config file or defaults to "
        f'"{Arguments.default_compiler}", remaining ARGUMENTS will be forwarded to the COMPILER',
    )

    homcc_args_namespace, compiler_args = parser.parse_known_args(args)
    homcc_args_dict = vars(homcc_args_namespace)

    show_dependencies_: Optional[bool] = homcc_args_dict.get("dependencies")

    compiler_or_argument: str = homcc_args_dict.pop("COMPILER_OR_ARGUMENT")  # either compiler or very first argument
    compiler_arguments: Arguments = Arguments.from_args(compiler_or_argument, compiler_args)

    # all remaining "show and exit" actions should be handled here:
    if show_dependencies_:
        show_dependencies(compiler_arguments)

    return homcc_args_dict, compiler_arguments


class ConnectionType(str, Enum):
    """Helper class to distinguish between different destination connection types"""

    TCP = "TCP"
    SSH = "SSH"


def parse_destination(destination: str) -> Dict[str, Optional[str]]:
    destination_dict: Dict[str, Optional[str]] = dict.fromkeys(["type", "host", "port", "user", "compression"], None)

    # host_pattern: str = r"^$"  # either name, ipv4 or ipv6 address

    # DESTINATION,COMPRESSION
    match: Optional[re.Match] = re.match(r"^(\S+),(\S+)$", destination)

    if match:
        destination, compression = match.groups()
        destination_dict["compression"] = compression

    # USER@HOST
    match = re.match(r"^(\w+)@(\w+)$", destination)

    if match:
        user, host = match.groups()
        destination_dict["type"] = ConnectionType.SSH
        destination_dict["user"] = user
        destination_dict["host"] = host
        return destination_dict

    # @HOST
    match = re.match(r"^@(\w+)$", destination)

    if match:
        destination_dict["type"] = ConnectionType.SSH
        host = match.group(1)
        destination_dict["host"] = host
        return destination_dict

    # HOST:PORT
    match = re.match(r"^([\w.]+):(\d+)$", destination)  # dummy IPv4 test; TODO: IPv6?

    if match:
        destination_dict["type"] = ConnectionType.TCP
        host, port = match.groups()
        destination_dict["host"] = host
        destination_dict["port"] = port
        return destination_dict

    # HOST
    # this is a pretty generous pattern, but we'll use it as a fallback and fail on connecting if provided faultily
    match = re.match(r"^(\S+)$", destination)

    if match:
        destination_dict["type"] = ConnectionType.TCP
        destination_dict["host"] = destination
        return destination_dict

    raise ValueError(
        f'Destination "{destination}" could not be parsed correctly, please provide it in the correct format!'
    )


def show_dependencies(arguments: Arguments):
    try:
        dependencies = find_dependencies(arguments)
    except CompilerError as err:
        sys.exit(err.returncode)

    source_files: List[str] = arguments.source_files

    print("Dependencies:")
    for dependency in dependencies:
        if dependency not in source_files:
            print(dependency)

    sys.exit(os.EX_OK)


# TODO: load config file
def load_config_file() -> str:
    return str()


def find_dependencies(arguments: Arguments) -> Set[str]:
    """get unique set of dependencies by calling the preprocessor and filtering the result"""
    try:
        # execute preprocessor command, e.g.: "g++ main.cpp -MM"
        result: ArgumentsExecutionResult = arguments.dependency_finding().execute(check=True)
    except subprocess.CalledProcessError as err:
        logger.error("Preprocessor error:\n%s", err.stderr)  # TODO(s.pirsch): fix doubled stderr message
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
