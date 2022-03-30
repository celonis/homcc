"""shared common functionality for server and client regarding compiler arguments"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess

from dataclasses import dataclass
from typing import Iterator, List, Optional

logger = logging.getLogger(__name__)
encoding: str = "utf-8"


@dataclass
class ArgumentsExecutionResult:
    """Information that the Execution of Arguments produces"""

    return_code: int
    stdout: str
    stderr: str

    @classmethod
    def from_process_result(cls, result: subprocess.CompletedProcess) -> ArgumentsExecutionResult:
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

    def __eq__(self, other) -> bool:
        if isinstance(other, Arguments):
            return self.args == other.args
        if isinstance(other, list):
            return self.args == other
        raise NotImplementedError

    def __iter__(self) -> Iterator:
        for arg in self.args:
            yield arg

    def __len__(self) -> int:
        return len(self.args)

    def __str__(self) -> str:
        return "[" + " ".join(self.args) + "]"

    @staticmethod
    def is_source_file(arg: str) -> bool:
        """check whether an argument looks like a source file"""
        # if we enable remote assembly, additionally allow file extension ".s"
        source_file_pattern: str = r"^\S+\.(i|ii|c|cc|cp|cpp|cxx|c\+\+|m|mm|mi|mii)$"  # e.g. "foo.cpp"
        return re.match(source_file_pattern, arg.lower()) is not None

    @staticmethod
    def is_object_file(arg: str) -> bool:
        """check whether an argument looks like an object file"""
        object_file_pattern: str = r"^\S+\.o$"  # e.g. "foo.o"
        return re.match(object_file_pattern, arg.lower()) is not None

    @staticmethod
    def is_executable(arg: str) -> bool:
        """check whether an argument is executable"""
        return shutil.which(arg) is not None

    @staticmethod
    def is_compiler(arg: str) -> bool:
        """check if an argument looks like a compiler"""
        if not arg.startswith("-") and not Arguments.is_source_file(arg) and not Arguments.is_object_file(arg):
            logger.debug("%s is used as compiler", arg)

            if not Arguments.is_executable(arg):
                logger.warning("Specified compiler %s is not an executable", arg)
            return True
        return False

    @classmethod
    def from_argv(cls, argv: List[str], compiler: Optional[str] = None) -> Arguments:
        # compiler as explicit second argument, e.g.: homcc_client.py g++ -c foo.cpp
        if Arguments.is_compiler(argv[1]):
            return Arguments(argv[1:])

        # unspecified compiler argument, e.g.: homcc_client.py -c foo.cpp
        arguments: Arguments = Arguments(argv)
        arguments.compiler = compiler or "cc"  # overwrite compiler with cc as fallback

        return arguments

    def is_sendable(self) -> bool:
        """determine if the current Arguments lead to a meaningful compilation on the server"""
        # if only the preprocessor should be executed or if no assembly step is required, do not send to server
        for arg in self.args[1:]:
            if arg in [self.no_assembly_arg] + self.preprocessor_args:
                return False

        if not self.source_files:
            logger.info("No source files given, can not distribute to server.")
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
            .add_arg("-M")  # output dependencies without system headers
            .add_arg("-MT")  # change target of the dependency generation
            .add_arg(self.preprocessor_target)
        )

    def no_linking(self) -> Arguments:
        """return copy of Arguments with no linking argument added"""
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
                if self.is_source_file(arg):
                    source_file_paths.append(arg)
                else:
                    logger.debug("Not adding '%s' as source file, as it doesn't match source file regex.", arg)

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

    def remove_source_file_args(self) -> Arguments:
        """removes source file args"""
        for source_file in self.source_files:
            self.remove_arg(source_file)

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
