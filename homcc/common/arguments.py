"""shared common functionality for server and client regarding compiler arguments"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess

from dataclasses import dataclass
from typing import Any, Iterator, List, Optional

logger = logging.getLogger(__name__)


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

    def __init__(self, compiler: Optional[str], args: List[str]):
        self._compiler: Optional[str] = compiler
        self._args: List[str] = args

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Arguments) and len(self) == len(other):
            return self.compiler == other.compiler and self.args == other.args
        if isinstance(other, list) and len(self) == len(other):
            return self.compiler == other[0] and self.args == other[1:]
        return False

    def __iter__(self) -> Iterator:
        yield self.compiler
        yield from self.args

    def __len__(self) -> int:
        return len(self.args) + 1

    def __str__(self) -> str:
        return f'[{self.compiler} {" ".join(self.args[1:])}]'

    def __repr__(self) -> str:
        return f"{self.__class__}({str(self)})"

    @classmethod
    def from_args(cls, args: List[str]) -> Arguments:
        if not args:
            raise ValueError("Not enough arguments supplied to construct Arguments")

        # compiler without arguments, e.g. ["g++"]
        if len(args) == 1:
            return cls(args[0], [])

        # compiler with arguments, e.g. ["g++", "foo.cpp", "-c"]
        return cls(args[0], args[1:])

    @classmethod
    def from_cli(cls, compiler_or_argument: str, args: List[str]) -> Arguments:
        # explicit compiler argument, e.g.: "homcc [OPTIONAL ARGUMENTS] g++ -c foo.cpp"
        if cls.is_compiler(compiler_or_argument):
            return cls(compiler_or_argument, args)

        # missing compiler argument, e.g.: "homcc [OPTIONAL ARGUMENTS] -c foo.cpp"
        return cls(None, [compiler_or_argument] + args)

    @staticmethod
    def is_source_file(arg: str) -> bool:
        """check whether an argument looks like a source file"""
        # if we enable remote assembly, additionally allow file extension ".s"
        source_file_pattern: str = r"^\S+\.(i|ii|c|cc|cp|cpp|cxx|c\+\+|m|mm|mi|mii)$"  # e.g. "foo.cpp"
        return re.match(source_file_pattern, arg, re.IGNORECASE) is not None

    @staticmethod
    def is_object_file(arg: str) -> bool:
        """check whether an argument looks like an object file"""
        object_file_pattern: str = r"^\S+\.o$"  # e.g. "foo.o"
        return re.match(object_file_pattern, arg, re.IGNORECASE) is not None

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

    def is_sendable(self) -> bool:
        """determine if the Arguments lead to a meaningful remote compilation"""

        def log_unsendable(message: str):
            logger.info("%s; cannot compile remotely", message)

        if not self.source_files:
            log_unsendable("no source files given")
            return False

        for arg in self.args:
            if not arg.startswith("-"):
                continue

            # prefix args
            if arg.startswith(self.Unsendable.assembler_options_prefix):  # "-Wa,"
                log_unsendable(f"[{arg}] must be local")  # TODO(s.pirsch): this is more detailed, fix in separate PR
                return False

            if arg.startswith(self.Unsendable.specs_prefix):  # "-specs="
                log_unsendable(f"[{arg}] overwrites spec strings")
                return False

            if arg.startswith(self.Unsendable.profile_generate_prefix):  # "-fprofile-generate="
                log_unsendable(f"[{arg}]  will emit profile info")
                return False

            # single args
            if arg == self.Unsendable.no_assembly_arg:  # "-S"
                log_unsendable(f"[{arg}] implies a no assembly call")
                return False

            if arg == self.Unsendable.rpo_arg:  # "-frepo"
                log_unsendable(f"[{arg}] will emit .rpo files")
                return False

            # arg families
            if arg in self.Unsendable.native_args:
                log_unsendable(f"[{arg}] optimizes for local machine")
                return False

            if arg in self.Unsendable.preprocessor_args:
                log_unsendable(f"[{arg}] implies a preprocessor only call")
                return False

            for profile_arg in self.Unsendable.profile_args:
                if arg.startswith(profile_arg):
                    log_unsendable(f"[{arg}] will emit or use profile info")
                    return False

        return True

    def is_linking(self) -> bool:
        """check whether the linking flag is present"""
        return self.no_linking_arg not in self.args

    @property
    def args(self) -> List[str]:
        return self._args

    def add_arg(self, arg: str) -> Arguments:
        """add argument, may introduce duplicated arguments"""
        self._args.append(arg)
        return self

    def remove_arg(self, arg: str) -> Arguments:
        """remove argument if present, may remove multiple matching arguments"""
        self._args = list(filter(lambda _arg: _arg != arg, self.args))
        return self

    @property
    def compiler(self) -> Optional[str]:
        return self._compiler

    @compiler.setter
    def compiler(self, compiler: str):
        self._compiler = compiler

    def dependency_finding(self) -> Arguments:
        """return Arguments with which to find dependencies via the preprocessor"""
        return (
            Arguments(self.compiler, self.args)
            .remove_arg(self.no_linking_arg)
            .remove_output_args()
            .add_arg("-M")  # output dependencies
            .add_arg("-MT")  # change target of the dependency generation
            .add_arg(self.preprocessor_target)
        )

    def no_linking(self) -> Arguments:
        """return copy of Arguments with output arguments removed and no linking argument added"""
        return Arguments(self.compiler, self.args).remove_output_args().add_arg(self.no_linking_arg)

    @property
    def output(self) -> Optional[str]:
        """if present, return the last specified output target"""
        output: Optional[str] = None

        it: Iterator[str] = iter(self.args)
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

        for arg in self.args:
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
                    logger.debug('Not adding "%s" as source file, as it doesn\'t match source file regex.', arg)

            other_open_arg = False

        return source_file_paths

    def remove_output_args(self) -> Arguments:
        """return modified Arguments with all output related arguments removed"""
        arguments: Arguments = Arguments(self.compiler, [])

        it: Iterator[str] = iter(self.args)
        for arg in it:
            if arg.startswith("-o"):
                # skip output related args
                if arg == "-o":
                    next(it, None)  # skip output target argument without raising an exception
            else:
                arguments.add_arg(arg)

        self._args = arguments.args
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
        capture_output: bool = kwargs.pop("capture_output", True)

        if "stdout" in kwargs or "stderr" in kwargs:
            capture_output = False

        if "shell" in kwargs:
            logger.error("Arguments currently does not support shell execution!")

        result: subprocess.CompletedProcess = subprocess.run(
            list(self), check=check, encoding="utf-8", capture_output=capture_output, **kwargs
        )
        return ArgumentsExecutionResult.from_process_result(result)
