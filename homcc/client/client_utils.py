"""
fundamental utility functions and Exception class for the homcc client to interact with the linux
command line and the specified compiler
"""
import logging
import os
import subprocess
import sys

from abc import ABC, abstractmethod
from argparse import ArgumentParser, Action, Namespace
from typing import Dict, List, Optional, Set, Tuple

from homcc.common.arguments import Arguments, ArgumentsExecutionResult
from homcc.common.hashing import hash_file_with_path
from homcc.common.messages import ObjectFile

logger = logging.getLogger(__name__)


class CompilerError(subprocess.CalledProcessError):
    """Error class to indicate unrecoverability for the client main function and provide error information that occurred
    during execution of compiler commands"""

    def __init__(self, err: subprocess.CalledProcessError):
        super().__init__(err.returncode, err.cmd, err.output, err.stderr)


class ShowAction(ABC, Action):
    """
    Abstract base class to ensure correct initialization of flag arguments that have the behavior of "show and exit"
    for argparse
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
    def __call__(self, *_):
        pass


class ShowVersion(ShowAction):
    """show version and exit"""

    def __call__(self, *_):
        print("homcc 0.0.1")
        sys.exit(os.EX_OK)


class ShowHosts(ShowAction):
    """show host list and exit"""

    def __call__(self, *_):
        print("localhost/12")
        sys.exit(os.EX_OK)


class ShowConcurrencyLevel(ShowAction):
    """show the concurrency level, as calculated from the host list, and exit"""

    def __call__(self, *_):
        print("12")
        sys.exit(os.EX_OK)


class ShowDependencies(ShowAction):
    """show the dependencies that would be sent to the server, as calculated from the given arguments, and exit"""

    def __call__(self, parser: ArgumentParser, namespace: Namespace, values, option_string: Optional[str] = None):
        # TODO
        namespace.dependencies = True


# class ClientArgumentParser(ArgumentParser):
#    def __init__(self):
#        pass


def parse_args(argv: List[str]) -> Tuple[Namespace, List[str]]:
    parser: ArgumentParser = ArgumentParser(
        description="homcc - Home-Office friendly distcc replacement",
        allow_abbrev=False,
        add_help=False,
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--help", "-h", action="help", help="show this help message and exit")
    group.add_argument("--version", "-v", action=ShowVersion)
    group.add_argument("--hosts", "--show-hosts", action=ShowHosts)
    group.add_argument("-j", action=ShowConcurrencyLevel)
    group.add_argument("--dependencies", "--scan--includes", action=ShowDependencies)

    # subparsers = parser.add_subparsers()
    # subparsers.add_parser("COMPILER OPTIONS")

    # parser.add_argument("--randomize", action="store_true", help="randomize the server list before execution")

    parser.add_argument(
        "--host",
        required=False,
        type=str,
        help="address of the remote compilation server",
    )

    parser.add_argument(
        "--port",
        required=False,
        type=int,
        help="port for connecting to remote compilation server",
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

    # capturing all remaining arguments via nargs=argparse.REMAINDER is sadly not working as intended here, so we use
    # the dummy "COMPILER_OR_ARGUMENT" argument for the automatically generated usage string instead and handle the
    # remaining, unknown arguments separately in the callee
    parser.add_argument(
        "COMPILER_OR_ARGUMENT",
        type=str,
        metavar="[COMPILER] ARGUMENTS",
        help=f"COMPILER, if not specified explicitly, is either read from the config file or defaults to "
        f'"{Arguments.default_compiler}", remaining ARGUMENTS will be forwarded to the COMPILER',
    )

    return parser.parse_known_args(argv)


# TODO
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
