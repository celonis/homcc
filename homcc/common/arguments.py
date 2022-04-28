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
    language_arg: str = "-x"

    include_args: List[str] = ["-I", "-isysroot", "-isystem"]

    class Local:
        """
        Class to encapsulate all argument types that are not meaningful during remote compilation and should therefore
        be removed before being sent.
        """

        # arguments with options
        option_args: List[str] = [
            "-D",
            # "-I",
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
            # "-I",
            "-l",
            "-L",
            "-MF",
            "-MT",
            "-MQ",
            "-isystem",
            "-stdlib",
        ]

        # arguments that only affect C++ compilation
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
        Class to encapsulate all argument types that are relevant for the Sendability test. Unsendability implies
        harmfulness during remote compilation, therefore if an Arguments instance does not fulfil Sendability, it should
        only be executed locally.
        """

        # languages
        allowed_language_prefixes: List[str] = ["c", "c++", "objective-c", "objective-c++", "go"]

        # preprocessing args
        preprocessing_only_arg: str = "-E"
        preprocessing_dependency_arg: str = "-M"
        allowed_preprocessing_args: List[str] = ["-MD", "-MMD", "-MG", "-MP"]
        allowed_preprocessing_option_args: List[str] = ["-MF", "-MT", "-MQ"]

        # args that rely on native machine
        native_args: List[str] = ["-march=native", "-mtune=native"]

        # assembly
        no_assembly_arg: str = "-S"
        assembler_options_prefix: str = "-Wa,"
        assembler_options: List[str] = [",-a", "--MD"]

        # specs
        specs_prefix: str = "-specs="

        # profile info
        profile_args: List[str] = [
            "-fprofile-arcs",
            "-ftest-coverage",
            "--coverage",
            "-fprofile-correction",
        ]
        profile_arg_prefixes: List[str] = [
            "-fprofile-generate",
            "-fprofile-use",
            "-fauto-profile",
        ]

        # rpo
        rpo_arg: str = "-frepo"

        # debug
        debug_arg_prefix: str = "-dr"

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
        return f'[{self.compiler} {" ".join(self.args)}]'

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

        # preprocessor args
        if arg == Arguments.Unsendable.preprocessing_only_arg:  # -E
            logger.debug("[%s] implies a preprocessor only call", arg)
            return False

        if arg in Arguments.Unsendable.allowed_preprocessing_args:
            return True

        if arg.startswith(tuple(Arguments.Unsendable.allowed_preprocessing_option_args)):
            return True

        if arg.startswith(Arguments.Unsendable.preprocessing_dependency_arg):  # -Moption
            logger.debug("[%s] implies [%s] and must be local", arg, Arguments.Unsendable.preprocessing_only_arg)
            return False  # all remaining preprocessing arg options imply Unsendability

        # native args
        if arg in Arguments.Unsendable.native_args:
            logger.debug("[%s] optimizes for local machine", arg)
            return False

        # assembly
        if arg == Arguments.Unsendable.no_assembly_arg:  # "-S"
            return False

        if arg.startswith(Arguments.Unsendable.assembler_options_prefix):  # "-Wa,"
            for assembler_option in Arguments.Unsendable.assembler_options:
                if assembler_option in arg:
                    logger.debug("[%s] must be local", arg)
                    return False

        # specs
        if arg.startswith(Arguments.Unsendable.specs_prefix):  # "-specs="
            logger.debug("[%s] overwrites spec strings", arg)
            return False

        # profile info
        if arg in Arguments.Unsendable.profile_args or arg.startswith(tuple(Arguments.Unsendable.profile_arg_prefixes)):
            logger.debug("[%s] will emit or use profile info", arg)
            return False

        # rpo
        if arg == Arguments.Unsendable.rpo_arg:  # "-frepo"
            logger.debug("[%s] will emit .rpo files", arg)
            return False

        # debug
        if arg.startswith(Arguments.Unsendable.debug_arg_prefix):  # "-dr"
            logger.debug("[%s] may imply creation of debug files", arg)
            return False

        return True

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

    @property
    def output(self) -> Optional[str]:
        """if present, return the last specified output target"""
        output: Optional[str] = None

        it: Iterator[str] = iter(self.args)
        for arg in it:
            if arg.startswith(self.output_arg):
                if arg == self.output_arg:  # output argument with output target following: e.g.: -o out
                    output = next(it)  # skip output target
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
                        next(it)

            elif self.is_source_file_arg(arg):
                source_files.append(arg)

            else:
                logger.debug('Not adding "%s" as source file, as it does not match source file regex.', arg)

        return source_files

    @property
    def specified_language(self) -> Optional[str]:
        it: Iterator[str] = iter(self.args)
        for arg in it:
            if arg.startswith(self.language_arg):
                return next(it)

        return None

    def is_sendable(self) -> bool:
        """check whether executing Arguments leads to a successful remote compilation"""
        # "-o -" might be treated as write result to stdout by some compilers
        output: Optional[str] = self.output
        if output == "-":
            logger.info('cannot compile %s remotely because output "%s" is ambiguous', self, output)
            return False

        # no source files
        if not self.source_files:
            logger.info("cannot compile %s remotely because no source files were given", self)
            return False

        # unknown language
        specified_language: Optional[str] = self.specified_language
        if specified_language is not None and not specified_language.startswith(
            tuple(Arguments.Unsendable.allowed_language_prefixes)
        ):
            logger.info("language handling is too complex for %s", specified_language)
            return False

        # complex unsendable arguments
        for arg in self.args:
            if not self.is_sendable_arg(arg):
                logger.info("cannot compile %s remotely due to argument [%s]", self, arg)
                return False

        return True

    def is_linking(self) -> bool:
        """check whether the linking flag is present"""
        return self.no_linking_arg not in self.args

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
                next(it)
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
                    next(it)  # skip output target
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
