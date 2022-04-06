"""shared common functionality for server and client regarding compiler arguments"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess

from dataclasses import dataclass
from typing import Any, Iterator, List, Optional

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

    Note: Most modifying methods assume sendability as modifications to the arguments are only required for remote
    compilation which implies arguments being able to be sent!
    """

    # if the compiler is neither specified by the callee nor defined in the config file use this as fallback
    default_compiler: str = "cc"

    no_linking_arg: str = "-c"
    output_arg: str = "-o"

    include_args: List[str] = ["-I", "-isysroot", "-isystem"]

    preprocessor_target: str = "$(homcc)"

    class Unsendable:
        """
        Class to encapsulate all args that imply unsendability.

        Note: Respect the naming scheme as listed in the comments below when additional arguments are added, so that the
        sendability test can deduce them automatically!
        """

        # arg prefixes: naming ends on _prefix
        assembler_options_prefix: str = "-Wa,"
        specs_prefix: str = "-specs="
        profile_generate_prefix: str = "-fprofile-generate="

        # single args: naming ends on _arg
        no_assembly_arg: str = "-S"
        assembler_options_arg: str = "-Xassembler"
        rpo_arg: str = "-frepo"

        # arg families: naming ends on _args
        native_args: List[str] = ["-march=native", "-mtune=native"]
        preprocessor_args: List[str] = ["-E", "-M", "-MM"]
        profile_args: List[str] = [
            "-fprofile-arcs",
            "-ftest-coverage",
            "--coverage",
            "-fprofile-generate",
            "-fprofile-use",
            "-fauto-profile",
            "-fprofile-correction",
        ]

    def __init__(self, args: List[str]):
        if len(args) <= 1:
            raise ValueError("Not enough arguments supplied to construct Arguments")

        self._args: List[str] = args

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Arguments):
            return self.args == other.args
        if isinstance(other, list):
            return self.args == other
        return False

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
    def from_args(cls, compiler_or_argument: str, args: List[str]) -> Arguments:
        # explicit compiler argument, e.g.: homcc_client.py [OPTIONAL ARGUMENTS] g++ -c foo.cpp
        if Arguments.is_compiler(compiler_or_argument):
            return Arguments([compiler_or_argument] + args)

        # missing compiler argument, e.g.: homcc_client.py [OPTIONAL ARGUMENTS] -c foo.cpp
        return Arguments([Arguments.default_compiler, compiler_or_argument] + args)

    def is_sendable(self) -> bool:
        """determine if the Arguments lead to a meaningful remote compilation"""
        return _is_sendable(self)

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

    def dependency_finding(self) -> Arguments:
        """return Arguments with which to find dependencies via the preprocessor"""
        return (
            Arguments(self.args)
            .remove_arg(self.no_linking_arg)
            .remove_output_args()
            .add_arg("-M")  # output dependencies
            .add_arg("-MT")  # change target of the dependency generation
            .add_arg(self.preprocessor_target)
        )

    def no_linking(self) -> Arguments:
        """return copy of Arguments with output arguments removed and no linking argument added"""
        return Arguments(self.args).remove_output_args().add_arg(self.no_linking_arg)

    @property
    def output(self) -> Optional[str]:
        """if present, return the last specified output target"""
        output: Optional[str] = None

        it: Iterator[str] = iter(self.args[1:])
        for arg in it:
            if arg.startswith("-o"):
                if arg == "-o":  # output argument with output target following: e.g.: -o out
                    try:
                        output = next(it)  # skip output target argument
                    except StopIteration as error:
                        logger.error("Faulty output arguments provided: %s", self)
                        raise ArgumentsOutputError from error
                else:  # compact output argument: e.g.: -oout
                    output = arg[2:]
        return output

    @output.setter
    def output(self, output: str):
        self.remove_output_args().add_arg(f"-o{output}")

    @property
    def source_files(self) -> List[str]:
        """extract files to be compiled and returns their paths"""
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
        """return modified Arguments with all output related arguments removed"""
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
        """remove source file args"""
        for source_file in self.source_files:
            self.remove_arg(source_file)

        return self

    def execute(self, **kwargs) -> ArgumentsExecutionResult:
        """
        execute the current arguments as command and return its execution result

        parameters:
        - check: enables the raising of CalledProcessError
        - cwd: changes the current working directory
        """
        check: bool = kwargs.pop("check", False)
        encoding_: str = kwargs.pop("encoding", encoding)
        capture_output: bool = kwargs.pop("capture_output", True)

        if "shell" in kwargs:
            logger.error("Arguments does currently not support shell execution!")

        result: subprocess.CompletedProcess = subprocess.run(
            self.args, check=check, encoding=encoding_, capture_output=capture_output, **kwargs
        )
        return ArgumentsExecutionResult.from_process_result(result)


# extracted is_sendable method to keep Arguments class more manageable and readable
def _is_sendable(arguments: Arguments) -> bool:
    def log_unsendable(message: str):
        logger.info("%s; cannot compile remotely", message)

    if not arguments.source_files:
        log_unsendable("no source files given")
        return False

    for arg in arguments.args[1:]:
        # prefix args
        if arg.startswith(Arguments.Unsendable.assembler_options_prefix):
            log_unsendable(f"[{arg}] TODO")  # TODO
            return False

        if arg.startswith(Arguments.Unsendable.specs_prefix):
            log_unsendable(f"[{arg}] TODO")  # TODO
            return False

        if arg.startswith(Arguments.Unsendable.profile_generate_prefix):
            log_unsendable(f"[{arg}] TODO")  # TODO
            return False

        # single args
        if arg == Arguments.Unsendable.no_assembly_arg:
            log_unsendable(f"[{arg}] implies a no assembly call")
            return False

        if arg == Arguments.Unsendable.assembler_options_arg:
            log_unsendable(f"[{arg}] TODO")  # TODO
            return False

        if arg == Arguments.Unsendable.rpo_arg:
            log_unsendable(f"[{arg}] will emit .rpo files")
            return False

        # arg families
        if arg in Arguments.Unsendable.native_args:
            log_unsendable(f"[{arg}] optimizes for local machine")
            return False

        if arg in Arguments.Unsendable.preprocessor_args:
            log_unsendable(f"[{arg}] implies a preprocessor only call")
            return False

        if arg in Arguments.Unsendable.profile_args or arg.startswith(Arguments.Unsendable.profile_generate_prefix):
            log_unsendable(f"[{arg}] will emit or use profile info")
            return False

    return True
