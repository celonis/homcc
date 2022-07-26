"""Tests for the compilers module of homcc."""
import pytest

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


class TestClang:
    """Tests the Clang class."""

    @pytest.mark.clangplusplus
    def test_get_target_triple(self):
        clang = Clang("clang++")
        assert clang.get_target_triple()  # check no exception is thrown and we got a non-empty string