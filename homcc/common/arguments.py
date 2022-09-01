"""shared common functionality for server and client regarding compiler arguments"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple, Type

from homcc.common.errors import TargetInferationError, UnsupportedCompilerError

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

    NO_LINKING_ARG: str = "-c"
    SHOW_COMPILER_STAGES: str = "-v"

    OUTPUT_ARG: str = "-o"
    SPECIFY_LANGUAGE_ARG: str = "-x"

    DEPENDENCY_SIDE_EFFECT_ARG: str = "-MD"

    INCLUDE_ARGS: List[str] = ["-I", "-isysroot", "-isystem"]

    # languages
    ALLOWED_LANGUAGE_PREFIXES: List[str] = ["c", "c++", "objective-c", "objective-c++", "go"]

    class Local:
        """
        Class to encapsulate all argument types that are not meaningful during remote compilation and should therefore
        be removed before being sent.
        """

        # preprocessor args
        PREPROCESSOR_ARGS: List[str] = ["-MG", "-MP"]
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
        PREPROCESSOR_USER_HEADER_ONLY_DEPENDENCY_ARG: str = "-MM"

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

    def __init__(self, compiler: Compiler, args: List[str]):
        """construct arguments from a list of args"""
        self._compiler: Compiler = compiler
        self._args: List[str] = args

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Arguments) and len(self) == len(other):
            return self.compiler == other.compiler and self.args == other.args
        if isinstance(other, list) and len(self) == len(other):
            # TODO: fix, all(i in list(self.compiler) for i in other?
            return list(self.compiler)[0] == other[0] and self.args == other[1:]
        return False

    def __iter__(self) -> Iterator[str]:
        yield from self.compiler
        yield from self.args

    def __len__(self) -> int:
        return len(self.args) + 1

    def __str__(self) -> str:
        return f"[{' '.join(list(self.compiler) + self.args)}]"

    def __repr__(self) -> str:
        return f"{self.__class__}({str(self)})"

    def copy(self) -> Arguments:
        """return an arguments copy"""
        return Arguments(self.compiler, self.args.copy())

    @classmethod
    def from_vargs(cls, *vargs: str) -> Arguments:
        """construct arguments from variadic str args"""
        if len(vargs) == 0:
            raise ValueError("Not enough args supplied to construct Arguments")

        return cls(Compiler.from_str(vargs[0]), list(vargs[1:]))

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
        """check whether an argument is a supported compiler"""
        if not arg.startswith("-") and not Arguments.is_source_file_arg(arg) and not Arguments.is_object_file_arg(arg):
            if Compiler.is_supported(arg):
                logger.debug("%s is used as compiler", arg)

                if not Arguments.is_executable_arg(arg):
                    # only warn the user here since compiler might still be an executable on the remote server
                    logger.warning("Specified compiler '%s' is not executable", arg)

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

        if arg in Arguments.Local.PREPROCESSOR_ARGS + [Arguments.DEPENDENCY_SIDE_EFFECT_ARG]:
            return True

        if arg.startswith(tuple(Arguments.Local.PREPROCESSOR_OPTION_PREFIX_ARGS)):
            return True

        if arg.startswith(Arguments.Unsendable.PREPROCESSOR_USER_HEADER_ONLY_DEPENDENCY_ARG):  # -MM prefix
            logger.debug("[%s] implies two different preprocessor calls", arg)
            return False

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

    @property
    def compiler(self) -> Compiler:
        """return the specified compiler"""
        return self._compiler

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
    def dependency_output(self) -> Optional[str]:
        """if present, return the last explicitly specified dependency output target"""
        dependency_output: Optional[str] = None

        it: Iterator[str] = iter(self.args)
        for arg in it:
            if arg.startswith("-MF"):
                if arg == "-MF":  # dependency output argument with output target following: e.g.: -MF out
                    dependency_output = next(it)  # skip dependency output file target
                else:  # compact dependency output argument: e.g.: -MFout
                    dependency_output = arg[3:]  # skip "-MF" prefix
        return dependency_output

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
        # "-o -" might either be treated as "write result to stdout" or "write result to file named '-'"
        if self.output == "-":
            logger.info("Cannot compile %s remotely because output '%s' is ambiguous", self, self.output)
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
                "Cannot compile %s remotely because handling of language '%s' is too complex",
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
        """check whether the no-linking arg is missing"""
        return self.NO_LINKING_ARG not in self.args

    def must_be_parsable(self) -> bool:
        """check whether the execution must be parsable and verbose logging should therefore be deactivated"""
        return self.SHOW_COMPILER_STAGES in self.args

    def map_symbol_paths(self, old_path: str, new_path: str) -> Arguments:
        """return a copy of arguments with added command for translating symbol paths in the executable
        See https://reproducible-builds.org/docs/build-path/.
        This maps debug symbols as well as macros such as __FILE__."""
        return self.copy().add_arg(f"-ffile-prefix-map={old_path}={new_path}")

    def is_linking_only(self) -> bool:
        """check whether the execution of arguments leads to calling only the linker"""
        if is_linking_only := not self.source_files and self.is_linking():
            logger.debug("%s is linking-only to '%s'", self, self.output)
        return is_linking_only

    def dependency_finding(self) -> Tuple[Arguments, Optional[str]]:
        """return a dependency finding arguments with which to find dependencies via the preprocessor"""

        # gcc and clang handle the combination of -MD -M differently, this function provides a uniform approach for
        # both compilers that also preserves side effects like the creation of dependency files

        if self.DEPENDENCY_SIDE_EFFECT_ARG not in self.args:
            # TODO(s.pirsch): benchmark -M -MF- and writing stdout to specified file afterwards
            return self.copy().remove_output_args().add_arg(self.Unsendable.PREPROCESSOR_DEPENDENCY_ARG), None

        dependency_output_file: str

        if self.dependency_output is not None:  # e.g. "-MF foo.d"
            dependency_output_file = self.dependency_output
        elif self.output is not None:  # e.g. "-o foo.o" -> "foo.d"
            dependency_output_file = f"{Path(self.output).stem}.d"
        else:  # e.g. "foo.cpp" -> "foo.d"
            dependency_output_file = f"{Path(self.source_files[0]).stem}.d"

        # TODO(s.pirsch): disallow multiple source files in the future when linker issue was investigated
        if len(self.source_files) > 1:
            logger.warning("Executing [%s] might not create the intended dependency files.", self)

        return self.copy().add_arg(self.Unsendable.PREPROCESSOR_DEPENDENCY_ARG), dependency_output_file

    def no_linking(self) -> Arguments:
        """return a copy of arguments where all output args are removed and the no linking arg is added"""
        return self.copy().remove_output_args().add_arg(self.NO_LINKING_ARG)

    def add_target(self, target: str) -> Arguments:
        """returns a copy of arguments where the specified target is added (for cross compilation)"""
        return self.compiler.add_target_to_arguments(self, target)

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
                logger.debug("Unmapped and possibly erroneous arg [%s]", arg)

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

    def get_compiler_target_triple(self) -> str:
        """returns the target triple for the given compiler"""
        return self.compiler.get_target_triple()

    @staticmethod
    def _execute_args(
        args: List[str],
        check: bool = False,
        cwd: Path = Path.cwd(),
        output: bool = False,
        timeout: Optional[float] = None,
    ) -> ArgumentsExecutionResult:
        logger.debug("Executing: [%s]", " ".join(args))

        result: subprocess.CompletedProcess = subprocess.run(
            args=args, check=check, cwd=cwd, encoding="utf-8", capture_output=True, timeout=timeout
        )

        if output:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)

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
        Execute arguments in a secure changed root environment. If possible, all parameters to this method will also be
        forwarded directly to the subprocess function call.
        """
        schroot_args: List[str] = ["schroot", "-c", profile, "--"]
        return self._execute_args(schroot_args + list(self), **kwargs)

    def docker_execute(self, container: str, cwd: str, **kwargs) -> ArgumentsExecutionResult:
        """
        Execute arguments in a docker container. If possible, all parameters to this method will also be forwarded
        directly to the subprocess function call.
        """
        docker_args: List[str] = ["docker", "exec", "--workdir", cwd, container]
        return self._execute_args(docker_args + list(self), **kwargs)


class Compiler(ABC):
    """Base class for compiler abstraction."""

    _compiler_str: str
    _prefix: Optional[str]

    def __init__(self, compiler_str: str):
        super().__init__()

        self._prefix = self.symlinked_to(compiler_str)
        self._compiler_str = self.normalize(compiler_str)  # TODO

    def __iter__(self) -> Iterator[str]:
        if self._prefix is not None:
            yield self._prefix
        yield self._compiler_str

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Compiler):
            return self._compiler_str == other._compiler_str
        if isinstance(other, str):
            return self._compiler_str == other
        return False

    @staticmethod
    def symlinked_to(compiler_str) -> Optional[str]:
        """check if the compiler is a symlink and if so, return the resolved path"""
        # e.g. g++ symlinked to /usr/lib/ccache/g++
        if os.path.islink(compiler_str):
            # os.path.realpath(Path(compiler_str).absolute())
            return str(Path(compiler_str).resolve())
        return None

    def __str__(self) -> str:
        return " ".join(self)

    @classmethod
    def from_str(cls, compiler_str: str) -> Compiler:
        for CompilerType in cls.available_compilers():  # pylint: disable=invalid-name
            if CompilerType.is_matching_str(compiler_str):
                return CompilerType(compiler_str)

        raise UnsupportedCompilerError(f"Compiler '{compiler_str}' is not supported.")

    @staticmethod
    def is_supported(compiler_str: str) -> bool:
        # pylint: disable=invalid-name
        return any(CompilerType.is_matching_str(compiler_str) for CompilerType in Compiler.available_compilers())

    @staticmethod
    def normalize(compiler_str: str) -> str:
        """normalize the compiler (remove path, keep just executable if a path is provided as compiler)"""
        normalized_compiler_str: str = Path(compiler_str).name  # e.g. /usr/bin/g++ -> g++
        logger.debug("Normalizing compiler '%s' to '%s'.", compiler_str, normalized_compiler_str)
        return normalized_compiler_str

    @staticmethod
    @abstractmethod
    def is_matching_str(compiler_str: str) -> bool:
        """Returns True if the given compiler string belongs to the certain compiler"""
        pass

    @abstractmethod
    def supports_target(self, target: str) -> bool:
        """Returns True if the compiler supports the given target for cross compilation."""
        pass

    @abstractmethod
    def get_target_triple(self) -> str:
        """Gets the target triple that the compiler produces on the machine. (e.g. x86_64-pc-linux-gnu)"""
        pass

    @abstractmethod
    def add_target_to_arguments(self, arguments: Arguments, target: str) -> Arguments:
        """Copies arguments so that the target is changed to the supplied target."""

    @staticmethod
    def available_compilers() -> List[Type[Compiler]]:
        """Returns a list of available compilers for homcc."""
        return Compiler.__subclasses__()


class Clang(Compiler):
    """Implements clang specific handling."""

    @staticmethod
    def is_matching_str(compiler_str: str) -> bool:
        return "clang" in compiler_str

    def supports_target(self, _: str) -> bool:
        """For clang, we can not really check if it supports the target prior to compiling:
        '$ clang --print-targets' does not output the same triple format as we get from
        '$ clang --version' (x86_64 vs. x86-64), so we can not properly check if a target is supported.
        Therefore, we can just assume clang can handle the target."""
        return True

    def get_target_triple(self) -> str:
        clang_arguments: Arguments = Arguments(self, ["--version"])

        try:
            result = clang_arguments.execute(check=True)
        except subprocess.CalledProcessError as err:
            logger.error(
                "Could not get target triple for compiler '%s', executed '%s'. %s",
                self._compiler_str,
                clang_arguments,
                err,
            )
            raise TargetInferationError from err

        if matches := re.findall("(?<=Target:).*?(?=\n)", result.stdout, re.IGNORECASE):
            return matches[0].strip()

        raise TargetInferationError("Could not infer target triple for clang. Nothing matches the regex.")

    def add_target_to_arguments(self, arguments: Arguments, target: str) -> Arguments:
        for arg in arguments.args:
            if arg.startswith("--target=") or arg == "-target":
                logger.info(
                    "Not adding target '%s' to compiler '%s', as (potentially another) target is already specified.",
                    target,
                    arguments.compiler,
                )
                return arguments

        return arguments.copy().add_arg(f"--target={target}")


class Gcc(Compiler):
    """Implements gcc specific handling."""

    @staticmethod
    def is_matching_str(compiler_str: str) -> bool:
        return "gcc" in compiler_str or ("g++" in compiler_str and "clang" not in compiler_str)

    def supports_target(self, target: str) -> bool:
        return shutil.which(f"{target}-{self._compiler_str}") is not None

    def get_target_triple(self) -> str:
        gcc_arguments: Arguments = Arguments(self, ["-dumpmachine"])

        try:
            result = gcc_arguments.execute(check=True)
        except subprocess.CalledProcessError as err:
            logger.error(
                "Could not get target triple for compiler '%s', executed '%s'. %s",
                self._compiler_str,
                gcc_arguments,
                err,
            )
            raise TargetInferationError from err

        return result.stdout.strip()

    def add_target_to_arguments(self, arguments: Arguments, target: str) -> Arguments:
        if target in str(arguments.compiler):
            logger.info(
                "Not adding target '%s' to compiler '%s', as target is already specified.", target, arguments.compiler
            )
            return arguments

        # e.g. g++ -> x86_64-linux-gnu-g++
        return Arguments(Compiler.from_str(f"{target}-{self._compiler_str}"), arguments.args)
