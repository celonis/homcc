"""Module containing code that abstracts different compilers."""
from __future__ import annotations
import re

import shutil
import logging
import subprocess
from abc import ABC, abstractmethod
from typing import List, Type
from homcc.common.arguments import Arguments

from homcc.common.errors import TargetInferationError, UnsupportedCompilerError

logger = logging.getLogger(__name__)


class Compiler(ABC):
    """Base class for compiler abstraction."""

    def __init__(self, compiler_str: str) -> None:
        super().__init__()
        self.compiler_str = compiler_str

    @staticmethod
    def from_str(compiler_str: str) -> Compiler:
        for compiler in Compiler.available_compilers():
            if compiler.is_matching_str(compiler_str):
                return compiler(compiler_str)

        raise UnsupportedCompilerError(f"Compiler '{compiler_str}' is not supported.")

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
        return compiler_str.startswith("clang")

    def supports_target(self, target: str) -> bool:
        """For clang, we can not really check if it supports the target prior to compiling:
        '$ clang print-targets' does not output the same triple format as we get from
        '$ clang --version' (x86_64 vs. x86-64), so we can not properly check if a target is supported.
        Therefore, we can just assume clang can handle the target."""
        return True

    def get_target_triple(self) -> str:
        clang_arguments = Arguments(self.compiler_str, ["--version"])

        try:
            result = clang_arguments.execute(check=True)
        except subprocess.CalledProcessError as err:
            logger.error(
                "Could not get target triple for compiler '%s', executed '%s'. %s",
                self.compiler_str,
                clang_arguments,
                err,
            )
            raise TargetInferationError from err

        matches: List[str] = re.findall("(?<=Target:).*?(?=\n)", result.stdout, re.IGNORECASE)

        if len(matches) == 0:
            raise TargetInferationError("Could not infer target triple for clang. Nothing matches the regex.")

        return matches[0].strip()

    def add_target_to_arguments(self, arguments: Arguments, target: str) -> Arguments:
        return arguments.copy().add_arg(f"--target={target}")


class Gcc(Compiler):
    """Implements gcc specific handling."""

    @staticmethod
    def is_matching_str(compiler_str: str) -> bool:
        return compiler_str.startswith("gcc") or compiler_str.startswith("g++")

    def supports_target(self, target: str) -> bool:
        return shutil.which(f"{target}-{self.compiler_str}") is not None

    def get_target_triple(self) -> str:
        gcc_arguments = Arguments(self.compiler_str, ["-dumpmachine"])

        try:
            result = gcc_arguments.execute(check=True)
        except subprocess.CalledProcessError as err:
            logger.error(
                "Could not get target triple for compiler '%s', executed '%s'. %s",
                self.compiler_str,
                gcc_arguments,
                err,
            )
            raise TargetInferationError from err

        return result.stdout.strip()

    def add_target_to_arguments(self, arguments: Arguments, target: str) -> Arguments:
        copied_arguments = arguments.copy()
        # e.g. g++ -> x86_64-linux-gnu-g++
        copied_arguments.compiler = f"{target}-{self.compiler_str}"
        return copied_arguments
