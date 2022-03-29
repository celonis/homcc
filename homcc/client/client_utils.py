"""
fundamental utility functions and Exception class for the homcc client to interact with the linux
command line and the specified compiler
"""

import hashlib
import logging
import subprocess

from pathlib import Path
from typing import Dict, List, Set

logger = logging.getLogger(__name__)
encoding: str = "utf-8"


class CompilerError(subprocess.CalledProcessError):
    """
    Error class to indicate unrecoverability for the client main function and provide error
    information that occurred during execution of compiler commands
    """

    def __init__(self, err: subprocess.CalledProcessError):
        super().__init__(err.returncode, err.cmd, err.output, err.stderr)


def find_dependencies(args: List[str]) -> Set[str]:
    """get unique set of dependencies by calling the preprocessor and filtering the result"""
    args = args.copy()

    # replace unwanted options with empty flags
    for i, arg in enumerate(args):
        if arg == "-c":  # remove no linking option
            args[i] = ""
        elif arg == "-o":  # remove output option + corresponding output file
            args[i] = ""
            args[i + 1] = ""

    # remove empty flags
    args = [arg for arg in args if arg != ""]

    # add option to get dependencies without system headers
    args.insert(1, "-MM")

    try:
        # execute preprocessor command, e.g.: "g++ -MM main.cpp"
        result: subprocess.CompletedProcess = subprocess.run(
            args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as err:
        logger.error("Preprocessor error of [%s]: %s", " ".join(err.cmd), err.stderr.decode(encoding))
        raise CompilerError(err) from None

    if result.stdout:
        logger.debug("Preprocessor result of [%s]:\n%s", " ".join(result.args), result.stdout.decode(encoding))

    # create unique set of dependencies by filtering the preprocessor result
    def filter_output_target_and_line_break(dependency: str):
        return not dependency.endswith(".o:") and dependency != "\\"

    return set(filter(filter_output_target_and_line_break, result.stdout.decode(encoding).split()))


def calculate_dependency_dict(dependencies: Set[str]) -> Dict[str, str]:
    """calculate dependency file hashes mapping to their corresponding absolute filenames"""

    def hash_file(path: str) -> str:
        return hashlib.sha1(Path(path).read_bytes()).hexdigest()

    return {hash_file(dependency): dependency for dependency in dependencies}


def local_compile(args: List[str]) -> int:
    """execute local compilation"""
    logger.warning("Compiling locally instead!")
    logger.debug("Compiler arguments: [%s]", " ".join(args))

    try:
        # execute compile command, e.g.: "g++ foo.cpp -o bar.o"
        result: subprocess.CompletedProcess = subprocess.run(
            args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as err:
        logger.error("Compiler error of [%s]:\n%s", " ".join(err.cmd), err.stderr.decode(encoding))
        return err.returncode

    if result.stdout:
        logger.debug("Compiler result of [%s]:\n%s", " ".join(result.args), result.stdout.decode(encoding))
    return result.returncode
