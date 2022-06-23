""" Tests for client/compilation.py"""
import pytest

import os
import shutil
import subprocess

from pathlib import Path
from typing import List, Set

from homcc.common.arguments import Arguments
from homcc.client.compilation import (
    compile_locally,
    find_dependencies,
    is_sendable_dependency,
    scan_includes,
)
from homcc.client.parsing import Host


class TestCompilation:
    """Tests for functions in client/compilation.py"""

    def test_scan_includes(self):
        arguments: Arguments = Arguments.from_args(
            ["g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp"]
        )

        includes: List[str] = scan_includes(arguments)

        assert len(includes) == 1
        assert "example/include/foo.h" in includes

    def test_is_sendable(self):
        assert is_sendable_dependency("./example/include/foo.h")
        assert is_sendable_dependency("./example/src/main.cpp")
        assert is_sendable_dependency("./example/src/foo.cpp")

        assert not is_sendable_dependency("/usr/include/stdio.h")
        assert not is_sendable_dependency("/usr/bin/../lib/gcc/x86_64-linux-gnu/9/../../../../include/c++/9/cstdlib")

    @staticmethod
    def find_dependencies_with_compiler(compiler: str):
        args: List[str] = [compiler, "-Iexample/include", "example/src/main.cpp"]
        dependencies: Set[str] = find_dependencies(Arguments.from_args(args))

        assert len(dependencies) == 2
        assert "example/src/main.cpp" in dependencies
        assert "example/include/foo.h" in dependencies

    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    def test_find_dependencies_gplusplus(self):
        self.find_dependencies_with_compiler("g++")

    @pytest.mark.skipif(shutil.which("clang++") is None, reason="clang++ is not installed")
    def test_find_dependencies_clangplusplus(self):
        self.find_dependencies_with_compiler("clang++")

    @staticmethod
    def find_dependencies_class_impl_with_compiler(compiler: str):
        args: List[str] = [compiler, "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp"]
        dependencies: Set[str] = find_dependencies(Arguments.from_args(args))

        assert len(dependencies) == 3
        assert "example/src/main.cpp" in dependencies
        assert "example/src/foo.cpp" in dependencies
        assert "example/include/foo.h" in dependencies

    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    def find_dependencies_with_class_impl_gplusplus(self):
        self.find_dependencies_class_impl_with_compiler("g++")

    @pytest.mark.skipif(shutil.which("clang++") is None, reason="clang++ is not installed")
    def find_dependencies_with_class_impl_clangplusplus(self):
        self.find_dependencies_class_impl_with_compiler("clang++")

    def test_find_dependencies_error(self):
        args: List[str] = ["g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp", "-OError"]

        with pytest.raises(SystemExit) as sys_exit:
            _: Set[str] = find_dependencies(Arguments.from_args(args))

        assert sys_exit.value.code != os.EX_OK

    def test_local_compilation(self):
        output: str = "compilation_test"
        args: List[str] = ["g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp", f"-o{output}"]

        assert not Path(output).exists()
        assert compile_locally(Arguments.from_args(args), Host.localhost_with_limit(1)) == os.EX_OK
        assert Path(output).exists()

        executable_stdout: str = subprocess.check_output([f"./{output}"], encoding="utf-8")
        assert executable_stdout == "homcc\n"

        Path(output).unlink(missing_ok=True)

        # intentionally execute an erroneous call
        assert compile_locally(Arguments.from_args(args + ["-OError"]), Host.localhost_with_limit(1)) != os.EX_OK
