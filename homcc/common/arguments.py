"""shared common functionality for server and client regarding compiler arguments"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess

from dataclasses import dataclass
from functools import cached_property
from typing import Any, Iterator, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ArgumentsExecutionResult:
    """Information that the execution of an Arguments instance produces"""

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

    # execution timeout
    TIMEOUT: int = 180

    # if the compiler is neither specified by the callee nor defined in the config file use this as fallback
    DEFAULT_COMPILER: str = "cc"
    PREPROCESSOR_TARGET: str = "$(homcc)"

    NO_LINKING_ARG: str = "-c"
    DEBUG_SYMBOLS_ARG: str = "-gs"
    OUTPUT_ARG: str = "-o"
    SPECIFY_LANGUAGE_ARG: str = "-x"


    INCLUDE_ARGS: List[str] = ["-I", "-isysroot", "-isystem"]

    # languages
    ALLOWED_LANGUAGE_PREFIXES: List[str] = ["c", "c++", "objective-c", "objective-c++", "go"]

    class Local:
        """
        Class to encapsulate all argument types that are not meaningful during remote compilation and should therefore
        be removed before being sent.
        """

        # preprocessor args
        PREPROCESSOR_ARGS: List[str] = ["-MD", "-MMD", "-MG", "-MP"]
        PREPROCESSOR_OPTION_PREFIX_ARGS: List[str] = ["-MF", "-MT", "-MQ"]

        # linking args
        LINKER_OPTION_PREFIX_ARGS: List[str] = ["-L", "-l", "-Wl,"]

    class Unsendable:
        """
        Class to encapsulate all argument types that are relevant for the Sendability test. Unsendability implies
        harmfulness during remote compilation, therefore if an Arguments instance does not fulfil Sendability, it should
        only be executed locally.
        """

        # preprocessing args
        PREPROCESSOR_ONLY_ARG: str = "-E"
        PREPROCESSOR_DEPENDENCY_ARG: str = "-M"

        # args that rely on native machine
        NATIVE_ARGS: List[str] = ["-march=native", "-mtune=native"]

        # assembly
        NO_ASSEMBLY_ARG: str = "-S"
        ASSEMBLER_OPTIONS_PREFIX: str = "-Wa,"
        ASSEMBLER_OPTIONS: List[str] = [",-a", "--MD"]

        # specs
        SPECS_PREFIX: str = "-specs="

        # profile info
        PROFILE_ARGS: List[str] = [
            "-fprofile-arcs",
            "-ftest-coverage",
            "--coverage",
            "-fprofile-correction",
        ]
        PROFILE_ARG_PREFIXES: List[str] = [
            "-fprofile-generate",
            "-fprofile-use",
            "-fauto-profile",
        ]

        # rpo
        RPO_ARG: str = "-frepo"

        # debug
        DEBUG_ARG_PREFIX: str = "-dr"

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

    def copy(self) -> Arguments:
        """return an arguments copy"""
        return Arguments(self.compiler, self.args.copy())

    @classmethod
    def from_args(cls, args: List[str]) -> Arguments:
        """construct arguments from a list of args"""
        if not args:
            raise ValueError("Not enough args supplied to construct Arguments")

        # singular arg, e.g. ["g++"] or ["foo.cpp"]
        if len(args) == 1:
            arg: str = args[0]
            return cls(arg, []) if cls.is_compiler_arg(arg) else cls(None, [arg])

        # compiler with args, e.g. ["g++", "foo.cpp", "-c"]
        return cls(args[0], args[1:])

    @classmethod
    def from_cli(cls, compiler_or_argument: str, args: List[str]) -> Arguments:
        """construct Arguments from args given via the CLI"""
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
                logger.warning("Specified compiler '%s' is not an executable", arg)
            return True
        return False

    @staticmethod
    def is_sendable_arg(arg: str) -> bool:
        """check whether an argument is sendable"""
        if not arg.startswith("-"):
            return True

        # preprocessor args
        if arg == Arguments.Unsendable.PREPROCESSOR_ONLY_ARG:  # -E
            logger.debug("[%s] implies a preprocessor only call", arg)
            return False

        if arg in Arguments.Local.PREPROCESSOR_ARGS:
            return True

        if arg.startswith(tuple(Arguments.Local.PREPROCESSOR_OPTION_PREFIX_ARGS)):
            return True

        # all remaining preprocessing arg types with prefix "-M" imply Unsendability
        if arg.startswith(Arguments.Unsendable.PREPROCESSOR_DEPENDENCY_ARG):
            logger.debug(
                "[%s] implies [%s] and must be executed locally", arg, Arguments.Unsendable.PREPROCESSOR_ONLY_ARG
            )
            return False

        # native args
        if arg in Arguments.Unsendable.NATIVE_ARGS:
            logger.debug("[%s] optimizes for local machine", arg)
            return False

        # assembly
        if arg == Arguments.Unsendable.NO_ASSEMBLY_ARG:  # "-S"
            return False

        if arg.startswith(Arguments.Unsendable.ASSEMBLER_OPTIONS_PREFIX):  # "-Wa,"
            for assembler_option in Arguments.Unsendable.ASSEMBLER_OPTIONS:
                if assembler_option in arg:
                    logger.debug("[%s] must be executed locally", arg)
                    return False

        # specs
        if arg.startswith(Arguments.Unsendable.SPECS_PREFIX):  # "-specs="
            logger.debug("[%s] overwrites spec strings", arg)
            return False

        # profile info
        if arg in Arguments.Unsendable.PROFILE_ARGS or arg.startswith(tuple(Arguments.Unsendable.PROFILE_ARG_PREFIXES)):
            logger.debug("[%s] will emit or use profile info", arg)
            return False

        # rpo
        if arg == Arguments.Unsendable.RPO_ARG:  # "-frepo"
            logger.debug("[%s] will emit .rpo files", arg)
            return False

        # debug
        if arg.startswith(Arguments.Unsendable.DEBUG_ARG_PREFIX):  # "-dr"
            logger.debug("[%s] may imply creation of debug files", arg)
            return False

        return True

    @staticmethod
    def map_path_arg(path_arg: str, instance_path: str, mapped_cwd: str) -> str:
        """Maps absolute or relative path from client to absolute path on the server."""
        joined_path: str = (
            # in case of an absolute path we have to remove the first "/"
            # otherwise os.path.join ignores the paths previous to this
            os.path.join(instance_path, path_arg[1:])
            if os.path.isabs(path_arg)
            else os.path.join(mapped_cwd, path_arg)
        )

        # remove any ".." or "." inside paths
        return os.path.realpath(joined_path)

    @property
    def args(self) -> List[str]:
        """return all non-compiler args"""
        return self._args

    def add_arg(self, arg: str) -> Arguments:
        """
        add the specified arg, this may introduce duplicated args and break cached properties when used inconsiderately
        """
        self._args.append(arg)
        return self

    def remove_arg(self, arg: str) -> Arguments:
        """
        if present, remove the specified arg, this may remove multiple occurrences of this arg and break cached
        properties when used inconsiderately
        """
        self._args = list(filter(lambda _arg: _arg != arg, self.args))
        return self

    @property
    def compiler(self) -> Optional[str]:
        """if present, return the specified compiler"""
        return self._compiler

    @compiler.setter
    def compiler(self, compiler: str):
        self._compiler = compiler

    @cached_property
    def output(self) -> Optional[str]:
        """if present, return the last specified output target"""
        output: Optional[str] = None

        it: Iterator[str] = iter(self.args)
        for arg in it:
            if arg.startswith(self.OUTPUT_ARG):
                if arg == self.OUTPUT_ARG:  # output argument with output target following: e.g.: -o out
                    output = next(it)  # skip output target
                else:  # compact output argument: e.g.: -oout
                    output = arg[2:]
        return output

    @cached_property
    def source_files(self) -> List[str]:
        """extract and return all source files that will be compiled"""
        source_files: List[str] = []

        it: Iterator[str] = iter(self.args)
        for arg in it:
            if arg.startswith("-"):
                for arg_prefix in [self.OUTPUT_ARG] + self.INCLUDE_ARGS:
                    if arg == arg_prefix:
                        next(it)

            elif self.is_source_file_arg(arg):
                source_files.append(arg)

            else:
                logger.debug("Not adding '%s' as source file, as it does not match source file regex.", arg)

        return source_files

    @cached_property
    def object_files(self) -> List[str]:
        """extract and return all object files that will be linked"""
        object_files: List[str] = []

        for arg in self.args:
            if not arg.startswith("-") and self.is_object_file_arg(arg):
                object_files.append(arg)

        return object_files

    @cached_property
    def specified_language(self) -> Optional[str]:
        """if present, return the specified language"""
        it: Iterator[str] = iter(self.args)
        for arg in it:
            if arg.startswith(self.SPECIFY_LANGUAGE_ARG):
                return next(it)

        return None

    def is_sendable(self) -> bool:
        """check whether the remote execution of arguments would be successful"""
        # "-o -" might be treated as "write result to stdout" by some compilers
        if self.output == "-":
            logger.info('Cannot compile %s remotely because output "%s" is ambiguous', self, self.output)
            return False

        # no source files
        if not self.source_files:
            logger.info("Cannot compile %s remotely because no source files were given", self)
            return False

        # unknown language
        if self.specified_language is not None and not self.specified_language.startswith(
            tuple(Arguments.ALLOWED_LANGUAGE_PREFIXES)
        ):
            logger.info(
                'Cannot compile %s remotely because handling of language "%s" is too complex',
                self,
                self.specified_language,
            )
            return False

        # complex unsendable arguments
        for arg in self.args:
            if not self.is_sendable_arg(arg):
                logger.info("Cannot compile %s remotely due to argument [%s]", self, arg)
                return False

        return True

    def is_linking(self) -> bool:
        """check whether the linking arg is present"""
        return self.NO_LINKING_ARG not in self.args

    def has_debug_symbols(self) -> bool:
        """check whether the -g flag is present"""
        return self.DEBUG_SYMBOLS_ARG in self.args

    def map_debug_symbol_paths(self, old_path: str, new_path: str) -> Arguments:
        """return a copy of arguments with added command for translating debug symbols in the executable"""
        return self.copy().add_arg(f"-fdebug-prefix-map={old_path}={new_path}")

    def is_linking_only(self) -> bool:
        """check whether the execution of arguments leads to calling only the linker"""
        return not self.source_files and self.is_linking()

    def dependency_finding(self) -> Arguments:
        """return a copy of arguments with which to find dependencies via the preprocessor"""
        return (
            self.copy()
            .remove_arg(self.NO_LINKING_ARG)
            .remove_output_args()
            .add_arg("-M")  # output dependencies
            .add_arg("-MT")  # change target of the dependency generation
            .add_arg(self.PREPROCESSOR_TARGET)
        )

    def no_linking(self) -> Arguments:
        """return a copy of arguments where all output args are removed and the no linking arg is added"""
        return self.copy().remove_output_args().add_arg(self.NO_LINKING_ARG)

    def map(self, instance_path: str, mapped_cwd: str) -> Arguments:
        """modify and return arguments by mapping relevant paths"""
        args: List[str] = []
        path_option_prefix_args: List[str] = [self.OUTPUT_ARG] + self.INCLUDE_ARGS

        it: Iterator[str] = iter(self.args)
        for arg in it:
            if arg in self.source_files:
                arg = self.map_path_arg(arg, instance_path, mapped_cwd)

            elif arg.startswith("-"):
                for path_arg in path_option_prefix_args:
                    if arg.startswith(path_arg):
                        path: str = next(it) if arg == path_arg else arg[len(path_arg) :]
                        arg = f"{path_arg}{self.map_path_arg(path, instance_path, mapped_cwd)}"

            else:
                logger.warning("Unmapped and possibly erroneous arg [%s]", arg)

            args.append(arg)

        self._args = args
        return self

    def remove_local_args(self) -> Arguments:
        """modify and return arguments by removing all remote compilation irrelevant args"""
        args: List[str] = []

        it: Iterator[str] = iter(self.args)
        for arg in it:
            if arg.startswith("-"):
                # skip preprocessing args
                if arg in Arguments.Local.PREPROCESSOR_ARGS:
                    continue

                if arg.startswith(tuple(Arguments.Local.PREPROCESSOR_OPTION_PREFIX_ARGS)):
                    if arg in Arguments.Local.PREPROCESSOR_OPTION_PREFIX_ARGS:
                        next(it)
                    continue

                # skip linking related args
                if arg.startswith(tuple(Arguments.Local.LINKER_OPTION_PREFIX_ARGS)):
                    if arg in Arguments.Local.LINKER_OPTION_PREFIX_ARGS:
                        next(it)
                    continue

            # keep remaining types of args
            args.append(arg)

        self._args = args
        return self

    def remove_output_args(self) -> Arguments:
        """modify and return arguments by removing all output related args"""
        args: List[str] = []

        it: Iterator[str] = iter(self.args)
        for arg in it:
            # skip output related args
            if arg.startswith(self.OUTPUT_ARG):
                if arg == self.OUTPUT_ARG:
                    next(it)  # skip output target
                continue

            args.append(arg)

        self.__dict__.pop("output", None)  # remove cached_property output
        self._args = args
        return self

    def remove_source_file_args(self) -> Arguments:
        """modify and return arguments by removing all source file args"""
        self.__dict__.pop("source_files", None)  # remove cached_property source_files
        self._args = [arg for arg in self.args if not self.is_source_file_arg(arg)]
        return self

    @staticmethod
    def _execute_args(args: List[str], **kwargs) -> ArgumentsExecutionResult:
        check: bool = kwargs.pop("check", False)
        capture_output: bool = kwargs.pop("capture_output", True)

        if "stdout" in kwargs or "stderr" in kwargs:
            capture_output = False

        if "shell" in kwargs:
            logger.error("Arguments currently does not support shell execution!")

        logger.debug("Executing: [%s]", " ".join(args))

        result: subprocess.CompletedProcess = subprocess.run(
            args=args, check=check, encoding="utf-8", capture_output=capture_output, timeout=Arguments.TIMEOUT, **kwargs
        )
        return ArgumentsExecutionResult.from_process_result(result)

    def execute(self, **kwargs) -> ArgumentsExecutionResult:
        """
        Execute arguments by forwarding it as a list of args to subprocess and return the result as an
        ArgumentsExecutionResult. If possible, all parameters to this method will also be forwarded directly to the
        subprocess function call.
        """
        return self._execute_args(list(self), **kwargs)

    def schroot_execute(self, profile: str, **kwargs) -> ArgumentsExecutionResult:
        """
        Execute arguments in a secure changed root environment by forwarding it as a list of args prepended by schroot
        args to subprocess and return the result as an ArgumentsExecutionResult. If possible, all parameters to this
        method will also be forwarded directly to the subprocess function call.
        """
        schroot_args: List[str] = ["schroot", "-c", profile, "--"]
        return self._execute_args(schroot_args + list(self), **kwargs)
