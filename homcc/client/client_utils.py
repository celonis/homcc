"""
fundamental utility functions and Exception class for the homcc client to interact with the linux
command line and the specified compiler
"""

import hashlib
import logging
import subprocess

from pathlib import Path
from typing import Dict, List, Set

from homcc.common.arguments import Arguments

logger = logging.getLogger(__name__)
encoding: str = "utf-8"


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
        # execute preprocessor command, e.g.: "g++ -MM main.cpp"
        result: subprocess.CompletedProcess = subprocess.run(list(arguments), check=True,
                                                             stdout=subprocess.PIPE,
                                                             stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as err:
        logger.error("Preprocessor error of [%s]: %s", ' '.join(err.cmd),
                     err.stderr.decode(encoding))
        raise CompilerError(err) from None

    if result.stdout:
        logger.debug("Preprocessor result of [%s]:\n%s", ' '.join(result.args),
                     result.stdout.decode(encoding))

    # create unique set of dependencies by filtering the preprocessor result
    def filter_output_target_and_line_break(dependency: str):
        return not dependency.endswith('.o:') and dependency != '\\'

    return set(filter(filter_output_target_and_line_break,
                      result.stdout.decode(encoding).split()))


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

    try:
        # execute linking command, e.g.: "g++ -ofoobar foo.o bar.o"
        result: subprocess.CompletedProcess = subprocess.run(list(arguments), check=True,
                                                             stdout=subprocess.PIPE,
                                                             stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as err:
        logger.error("Linking error of [%s]:\n%s", ' '.join(err.cmd), err.stderr.decode(encoding))
        return err.returncode

    if result.stdout:
        logger.debug("Linking result of [%s]:\n%s", ' '.join(result.args),
                     result.stdout.decode(encoding))
    return result.returncode


def local_compile(arguments: Arguments) -> int:
    """ execute local compilation """
    logger.warning("Compiling locally instead!")
    logger.debug("Compiler arguments: [%s]", ' '.join(arguments))

    try:
        # execute compile command, e.g.: "g++ foo.cpp -o bar.o"
        result: subprocess.CompletedProcess = subprocess.run(list(arguments), check=True,
                                                             stdout=subprocess.PIPE,
                                                             stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as err:
        logger.error("Compiler error of [%s]:\n%s", ' '.join(err.cmd), err.stderr.decode(encoding))
        return err.returncode

    if result.stdout:
        logger.debug("Compiler result of [%s]:\n%s", ' '.join(result.args),
                     result.stdout.decode(encoding))
    return result.returncode
