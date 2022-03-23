"""
fundamental utility functions and Exception class for the homcc client to interact with the linux
command line and the specified compiler
"""

import hashlib
import logging
import subprocess

from pathlib import Path
from typing import Dict, Set

from homcc.common.arguments import Arguments, ArgumentsExecutionResult

logger = logging.getLogger(__name__)


class CompilerError(subprocess.CalledProcessError):
    """
    Error class to indicate unrecoverability for the client main function and provide error
    information that occurred during execution of compiler commands
    """

    def __init__(self, err: subprocess.CalledProcessError):
        super().__init__(err.returncode, err.cmd, err.output, err.stderr)


def find_dependencies(arguments: Arguments) -> Set[str]:
    """ get unique set of dependencies by calling the preprocessor and filtering the result """
    try:
        # execute preprocessor command, e.g.: "g++ main.cpp -MM"
        result: ArgumentsExecutionResult = arguments.dependency_finding().execute(check=True)
    except subprocess.CalledProcessError as err:
        logger.error("Preprocessor error:\n%s", err.stderr)  # TODO: fix double output
        raise CompilerError(err) from err

    if result.stdout:
        logger.debug("Preprocessor result:\n%s", result.stdout)

    # create unique set of dependencies by filtering the preprocessor result
    def filter_preprocessor_target_and_line_break(dependency: str):
        return dependency not in [f"{Arguments.preprocessor_target}:", "\\"]

    return set(filter(filter_preprocessor_target_and_line_break, result.stdout.split()))


def calculate_dependency_dict(dependencies: Set[str]) -> Dict[str, str]:
    """ calculate dependency file hashes mapping to their corresponding absolute filenames """

    def hash_file(path: str) -> str:
        return hashlib.sha1(Path(path).read_bytes()).hexdigest()

    return {hash_file(dependency): dependency for dependency in dependencies}


def link_object_files(arguments: Arguments) -> int:
    """link all object files compiled by the server"""
    source_file_to_object_file_map: Dict[str, str] = dict(
        zip(arguments.source_files,
            [str(Path(source_file).with_suffix(".o")) for source_file in arguments.source_files])
    )
    arguments.replace_source_files_with_object_files(source_file_to_object_file_map)

    logger.debug("Linking!")
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
    """ execute local compilation """
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
