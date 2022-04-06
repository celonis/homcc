"""
fundamental utility functions and Exception class for the homcc client to interact with the linux
command line and the specified compiler
"""

import logging
import subprocess

from typing import Dict, Set, List

from homcc.common.arguments import Arguments, ArgumentsExecutionResult
from homcc.common.hashing import hash_file_with_path
from homcc.common.messages import ObjectFile

logger = logging.getLogger(__name__)


class CompilerError(subprocess.CalledProcessError):
    """Error class to indicate unrecoverability for the client main function and provide error information that occurred
    during execution of compiler commands"""

    def __init__(self, err: subprocess.CalledProcessError):
        super().__init__(err.returncode, err.cmd, err.output, err.stderr)


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


def local_compile(arguments: Arguments) -> int:
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
