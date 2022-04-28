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
    preprocessor_target: str = "$(homcc)"

    no_linking_arg: str = "-c"
    output_arg: str = "-o"

    include_args: List[str] = ["-I", "-isysroot", "-isystem"]

    class Local:
        """
        Class to encapsulate all argument types that are only meaningful for local compilation and should therefore be
        removed before being sent to the server.
        """

        # arguments with options
        option_args: List[str] = [
            "-D",
            "-I",
            "-U",
            "-L",
            "-l",
            "-MF",
            "-MT",
            "-MQ",
            "-include",
            "-imacros",
            "-iprefix",
            "-iwithprefix",
            "-isystem",
            "-iwithprefixbefore",
            "-idirafter",
        ]

        # prefixed arguments
        arg_prefixes: List[str] = [
            "-Wp,",
            "-Wl,",
            "-D",
            "-U",
            "-I",
            "-l",
            "-L",
            "-MF",
            "-MT",
            "-MQ",
            "-isystem",
            "-stdlib",
        ]

        # arguments that only affect cpp compilation
        cpp_args: List[str] = [
            "-undef",
            "-nostdinc",
            "-nostdinc++",
            "-MD",
            "-MMD",
            "-MG",
            "-MP",
        ]

    class Unsendable:
        """
        Class to encapsulate all argument types that would lead to errors during remote compilation and should therefore
        only be executed locally.
        """

        # Note: Respect the naming scheme as listed in the comments below when adding more arguments, so that tests can
        # be deduced automatically!

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

        for arg in self.args:
            yield arg

    def __len__(self) -> int:
        return len(self.args) + 1

    def __str__(self) -> str:
        return f'[{self.compiler} {" ".join(self.args)}]'

    def __repr__(self) -> str:
        return f"{self.__class__}({str(self)})"

    @classmethod
    def from_args(cls, args: List[str]) -> Arguments:
        if len(args) == 0:
            raise ValueError("Not enough arguments supplied to construct Arguments")

        # compiler without arguments, e.g. ["g++"]
        if len(args) == 1:
            return cls(args[0], [])

        # compiler with arguments, e.g. ["g++", "foo.cpp", "-c"]
        return cls(args[0], args[1:])

    @classmethod
    def from_cli(cls, compiler_or_argument: str, args: List[str]) -> Arguments:
        # explicit compiler argument, e.g.: "homcc [OPTIONAL ARGUMENTS] g++ -c foo.cpp"
        if cls.is_compiler_arg(compiler_or_argument):
            return cls(compiler_or_argument, args)

        # missing compiler argument, e.g.: "homcc [OPTIONAL ARGUMENTS] -c foo.cpp"
        return cls(None, [compiler_or_argument] + args)

    @staticmethod
    def is_source_file_arg(arg: str) -> bool:
        """check whether an argument looks like a source file"""
        # if we enable remote assembly, additionally allow file extension ".s"
        source_file_pattern: str = r"^\S+\.(i|ii|c|cc|cp|cpp|cxx|c\+\+|m|mm|mi|mii)$"  # e.g. "foo.cpp"
        return re.match(source_file_pattern, arg, re.IGNORECASE) is not None

    @staticmethod
    def is_object_file_arg(arg: str) -> bool:
        """check whether an argument looks like an object file"""
        object_file_pattern: str = r"^\S+\.o$"  # e.g. "foo.o"
        return re.match(object_file_pattern, arg, re.IGNORECASE) is not None

    @staticmethod
    def is_executable_arg(arg: str) -> bool:
        """check whether an argument is executable"""
        return shutil.which(arg) is not None

    @staticmethod
    def is_compiler_arg(arg: str) -> bool:
        """check whether an argument looks like a compiler"""
        if not arg.startswith("-") and not Arguments.is_source_file_arg(arg) and not Arguments.is_object_file_arg(arg):
            logger.debug("%s is used as compiler", arg)

            if not Arguments.is_executable_arg(arg):
                logger.warning("Specified compiler %s is not an executable", arg)
            return True
        return False

    @staticmethod
    def is_sendable_arg(arg: str) -> bool:
        """check whether an argument is sendable"""
        if not arg.startswith("-"):
            return True

        # prefix args
        if arg.startswith(Arguments.Unsendable.assembler_options_prefix):  # "-Wa,"
            logger.info("[%s] must be local", arg)  # TODO(s.pirsch): this is more detailed, fix in separate PR
            return False

        if arg.startswith(Arguments.Unsendable.specs_prefix):  # "-specs="
            logger.info("[%s] overwrites spec strings", arg)
            return False

        if arg.startswith(Arguments.Unsendable.profile_generate_prefix):  # "-fprofile-generate="
            logger.info("[%s]  will emit profile info", arg)
            return False

        # single args
        if arg == Arguments.Unsendable.no_assembly_arg:  # "-S"
            logger.info("[%s] implies a no assembly call", arg)
            return False

        if arg == Arguments.Unsendable.rpo_arg:  # "-frepo"
            logger.info("[%s] will emit .rpo files", arg)
            return False

        # arg families
        if arg in Arguments.Unsendable.native_args:
            logger.info("[%s] optimizes for local machine", arg)
            return False

        if arg in Arguments.Unsendable.preprocessor_args:
            logger.info("[%s] implies a preprocessor only call", arg)
            return False

        for profile_arg in Arguments.Unsendable.profile_args:
            if arg.startswith(profile_arg):
                logger.info("[%s] will emit or use profile info", arg)
                return False

        return True

    def is_sendable(self) -> bool:
        """determine if the Arguments lead to a meaningful remote compilation"""
        if not self.source_files:
            logger.warning("no source files given")
            logger.info("cannot compile %s remotely", self)
            return False

        for arg in self.args:
            if not self.is_sendable_arg(arg):
                logger.info("cannot compile %s remotely due to argument [%s]", self, arg)
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
            if arg.startswith(self.output_arg):
                if arg == self.output_arg:  # output argument with output target following: e.g.: -o out
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
        self.remove_output_args().add_arg(f"{self.output_arg}{output}")

    @property
    def source_files(self) -> List[str]:
        """extract files to be compiled and returns their paths"""
        source_files: List[str] = []

        it: Iterator[str] = iter(self.args)
        for arg in it:
            if arg.startswith("-"):
                for arg_prefix in [self.output_arg] + self.include_args:
                    if arg == arg_prefix:
                        next(it, None)

            elif self.is_source_file_arg(arg):
                source_files.append(arg)

            else:
                logger.debug('Not adding "%s" as source file, as it does not match source file regex.', arg)

        return source_files

    def remove_local_args(self) -> Arguments:
        """return modified Arguments with all local related arguments removed"""
        arguments: Arguments = Arguments(self.compiler, [])

        it: Iterator[str] = iter(self.args)
        for arg in it:
            # keep object and source files
            if not arg.startswith("-"):
                arguments.add_arg(arg)
                continue

            # skip local args and its following option
            if arg in Arguments.Local.option_args:
                next(it, None)
                continue

            # skip prefixed local args
            if arg.startswith(tuple(Arguments.Local.arg_prefixes)):
                continue

            # skip local args that only affect cpp
            if arg in Arguments.Local.cpp_args:
                continue

            # keep remaining types of args
            arguments.add_arg(arg)

        self._args = arguments.args
        return self

    def remove_output_args(self) -> Arguments:
        """return modified Arguments with all output related arguments removed"""
        arguments: Arguments = Arguments(self.compiler, [])

        it: Iterator[str] = iter(self.args)
        for arg in it:
            # skip output related args
            if arg.startswith(self.output_arg):
                if arg == self.output_arg:
                    next(it, None)  # skip output target
                continue

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
        Execute Arguments by forwarding it as a list of args to subprocess and return the result as an
        ArgumentsExecutionResult. All parameters to this method will also be forwarded as parameters to the subprocess
        function call if possible.
        """
        check: bool = kwargs.pop("check", False)
        capture_output: bool = kwargs.pop("capture_output", True)

        if "stdout" in kwargs or "stderr" in kwargs:
            capture_output = False

        if "shell" in kwargs:
            logger.error("Arguments currently does not support shell execution!")

        result: subprocess.CompletedProcess = subprocess.run(
            args=list(self), check=check, encoding="utf-8", capture_output=capture_output, **kwargs
        )
        return ArgumentsExecutionResult.from_process_result(result)
