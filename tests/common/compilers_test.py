"""Tests for the compilers module of homcc."""
import pytest
from homcc.common.arguments import Arguments

from homcc.common.compilers import Compiler, Clang, Gcc
from homcc.common.errors import UnsupportedCompilerError


class TestCompiler:
    """Tests the compiler class of homcc."""

    def test_from_str(self):
        assert isinstance(Compiler.from_str("gcc"), Gcc)
        assert isinstance(Compiler.from_str("gcc-11"), Gcc)
        assert isinstance(Compiler.from_str("g++"), Gcc)
        assert isinstance(Compiler.from_str("g++-11"), Gcc)
        assert isinstance(Compiler.from_str("/usr/lib/ccache/gcc-11"), Gcc)

        assert isinstance(Compiler.from_str("clang++"), Clang)
        assert isinstance(Compiler.from_str("clang++-11"), Clang)
        assert isinstance(Compiler.from_str("/usr/lib/ccache/clang-14"), Clang)

        with pytest.raises(UnsupportedCompilerError):
            Compiler.from_str("unknown++")


class TestGcc:
    """Tests the Gcc class."""

    @pytest.mark.gplusplus
    def test_supports_target(self):
        gcc = Gcc("g++")
        assert gcc.supports_target("x86_64-linux-gnu")
        assert not gcc.supports_target("other_arch-linux-gnu")

    @pytest.mark.gplusplus
    def test_get_target_triple(self):
        gcc = Gcc("g++")
        assert gcc.get_target_triple()  # check no exception is thrown and we got a non-empty string

    def test_add_target_to_arguments(self):
        gcc = Gcc("g++")

        arguments = Arguments.from_args(["g++", "-Iexample/include", "example/src/*"])
        new_arguments = gcc.add_target_to_arguments(arguments, "x86_64")
        assert new_arguments.compiler == "x86_64-g++"

        arguments = Arguments.from_args(["x86_64-g++-11", "-Iexample/include", "example/src/*"])
        new_arguments = gcc.add_target_to_arguments(arguments, "x86_64")
        assert new_arguments.compiler == "x86_64-g++-11"  # do not substitute if already substituted


class TestClang:
    """Tests the Clang class."""

    @pytest.mark.clangplusplus
    def test_get_target_triple(self):
        clang = Clang("clang++")
        assert clang.get_target_triple()  # check no exception is thrown and we got a non-empty string

    def test_add_target_to_arguments(self):
        clang = Clang("clang++")

        arguments = Arguments.from_args(["clang++", "-Iexample/include", "example/src/*"])
        new_arguments = clang.add_target_to_arguments(arguments, "x86_64")
        assert "--target=x86_64" in new_arguments.args

        arguments = Arguments.from_args(["clang++", "-Iexample/include", "example/src/*", "--target=aarch64"])
        new_arguments = clang.add_target_to_arguments(arguments, "x86_64")
        assert "--target=aarch64" in new_arguments.args
        assert "--target=x86_64" not in new_arguments.args

        arguments = Arguments.from_args(["clang++", "-Iexample/include", "example/src/*", "-target", "aarch64"])
        new_arguments = clang.add_target_to_arguments(arguments, "x86_64")
        assert "aarch64" in new_arguments.args
        assert "--target=x86_64" not in new_arguments.args
