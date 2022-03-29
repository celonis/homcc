"""shared common functionality for server and client regarding compiler arguments"""
from __future__ import annotations

import logging
import re
import subprocess

from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)
encoding: str = "utf-8"


@dataclass
class ArgumentsExecutionResult:
    """Information that the Execution of Arguments produces"""

    return_code: int
    stdout: str
    stderr: str

    @classmethod
    def from_process_result(cls, result: subprocess.CompletedProcess):
        return cls(result.returncode, result.stdout, result.stderr)


class ArgumentsOutputError(Exception):
    """Exception for failing to extract output target"""


class Arguments:
    """
    Class to encapsulate and produce compiler arguments.
    Note that most modifying methods assume sendability as modifications to the arguments are only required for
    non-local compilation which implies arguments being sent!
    """

    no_assembly_arg: str = "-S"
    no_linking_arg: str = "-c"
    output_arg: str = "-o"

    include_args: List[str] = ["-I", "-isysroot", "-isystem"]
    preprocessor_args: List[str] = ["-E", "-M", "-MM"]

    preprocessor_target: str = "$(homcc)"

    def __init__(self, args: List[str]):
        self._args: List[str] = args

    def __eq__(self, other):
        if isinstance(other, Arguments):
            return self.args == other.args
        if isinstance(other, list):
            return self.args == other
        raise NotImplementedError

    def __iter__(self) -> Iterator:
        for arg in self.args:
            yield arg

    def __len__(self):
        return len(self.args)

    def __str__(self):
        return "[" + " ".join(self.args) + "]"

    def is_sendable(self) -> bool:
        """determine if the current Arguments lead to a meaningful compilation on the server"""
        # if only the preprocessor should be executed or if no assembly step is required, do not send to server
        for arg in self.args[1:]:
            if arg in [self.no_assembly_arg] + self.preprocessor_args:
                return False
        return True

    def is_linking(self) -> bool:
        """check whether the linking flag is present"""
        return not self.has_arg(self.no_linking_arg)

    @property
    def args(self) -> List[str]:
        return self._args

    def has_arg(self, arg: str) -> bool:
        """check whether a specific arg is present"""
        return arg in self.args

    def add_arg(self, arg: str) -> Arguments:
        """add argument, may introduce duplicated arguments"""
        self._args.append(arg)
        return self

    def remove_arg(self, arg: str) -> Arguments:
        """remove argument if present, may remove multiple matching arguments"""
        self._args = list(filter(lambda _arg: _arg != arg, self.args))
        return self

    @property
    def compiler(self) -> str:
        return self.args[0]

    @compiler.setter
    def compiler(self, compiler: str):
        self._args[0] = compiler

    def dependency_finding(self) -> Arguments:
        """return Arguments with which to find dependencies via the preprocessor"""
        return (
            Arguments(self.args)
            .remove_arg(self.no_linking_arg)
            .remove_output_args()
            .add_arg("-MM")  # output dependencies without system headers
            .add_arg("-MT")  # change target of the dependency generation
            .add_arg(self.preprocessor_target)
        )

    def no_linking(self) -> Arguments:
        """return copy of Arguments with no linking argument added"""
        # with only one source file, both -o and -c arguments can be specified
        if len(self.source_files) == 1:
            return Arguments(self.args).add_arg(self.no_linking_arg)

        # remove -o arguments if multiple source files are provided
        return Arguments(self.args).remove_output_args().add_arg(self.no_linking_arg)

    @property
    def output(self) -> Optional[str]:
        """if present, returns the last specified output target"""
        output: Optional[str] = None

        it: Iterator[str] = iter(self.args[1:])
        for arg in it:
            if arg.startswith("-o"):
                if arg == "-o":  # output flag with following output argument: -o out
                    try:
                        output = next(it)  # skip output target argument
                    except StopIteration as error:
                        logger.error("Faulty output arguments provided: %s", self)
                        raise ArgumentsOutputError from error
                else:  # compact output argument: -oout
                    output = arg[2:]
        return output

    @output.setter
    def output(self, output: str):
        self.remove_output_args().add_arg(f"-o{output}")

    @property
    def source_files(self) -> List[str]:
        """extracts files to be compiled and returns their paths"""
        source_file_paths: List[str] = []
        source_file_pattern: str = r"^\S+\.(c|cc|cp|cpp|cxx|c\+\+)$"  # e.g. foo.cpp
        other_open_arg: bool = False

        for arg in self.args[1:]:
            if arg.startswith("-"):
                for arg_prefix in [self.output_arg] + self.include_args:
                    if arg == arg_prefix:
                        other_open_arg = True
                        break

                if other_open_arg:
                    continue

            elif not other_open_arg:
                if not re.match(source_file_pattern, arg.lower()):
                    logger.debug("Suspicious source file added: %s", arg)
                source_file_paths.append(arg)

            other_open_arg = False

        return source_file_paths

    def remove_output_args(self) -> Arguments:
        """returns modified Arguments with all output related arguments removed"""
        args: List[str] = [self.args[0]]

        it: Iterator[str] = iter(self.args[1:])
        for arg in it:
            if arg.startswith("-o"):
                # skip output related args
                if arg == "-o":
                    next(it, None)  # skip output target argument without raising an exception
            else:
                args.append(arg)

        self._args = args
        return self

    def replace_source_files_with_object_files(self, source_file_to_object_file_map: Dict[str, str]) -> Arguments:
        """returns modified Arguments with all source file paths replaced with their respective object file paths"""
        for i, arg in enumerate(self.args[1:]):
            if arg in source_file_to_object_file_map.keys():
                self._args[i + 1] = source_file_to_object_file_map[arg]  # +1 offset due to skipping compiler arg

        return self

    def execute(self, check: bool = False, cwd: Optional[str] = None) -> ArgumentsExecutionResult:
        """
        execute the current arguments as command and return its execution result

        parameters:
        - check: enables the raising of CalledProcessError
        - cwd: changes the current working directory
        """
        logger.debug("Executing %s", self)
        result: subprocess.CompletedProcess = subprocess.run(
            self.args, check=check, cwd=cwd, encoding=encoding, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return ArgumentsExecutionResult.from_process_result(result)
