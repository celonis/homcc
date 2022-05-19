""" Tests for client/compilation.py"""
import pytest

import os
import subprocess

from pathlib import Path
from typing import List, Set

from homcc.common.arguments import Arguments
from homcc.client.compilation import (
    DEFAULT_LOCALHOST,
    compile_locally,
    find_dependencies,
    scan_includes,
)


class TestCompilation:
    """Tests for functions in client/compilation.py"""

    def test_scan_includes(self):
        arguments: Arguments = Arguments.from_args(
            ["g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp"]
        )

        includes: List[str] = scan_includes(arguments)

        assert len(includes) == 1
        assert "example/include/foo.h" in includes

    def test_find_dependencies_without_class_impl(self):
        args: List[str] = ["g++", "-Iexample/include", "example/src/main.cpp"]
        dependencies: Set[str] = find_dependencies(Arguments.from_args(args))

        assert len(dependencies) == 2
        assert "example/src/main.cpp" in dependencies
        assert "example/include/foo.h" in dependencies

    def test_find_dependencies_with_class_impl(self):
        args: List[str] = ["g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp"]
        dependencies: Set[str] = find_dependencies(Arguments.from_args(args))

        assert len(dependencies) == 3
        assert "example/src/main.cpp" in dependencies
        assert "example/src/foo.cpp" in dependencies
        assert "example/include/foo.h" in dependencies

    def test_find_dependencies_error(self):
        args: List[str] = ["g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp", "-OError"]

        with pytest.raises(SystemExit) as sys_exit:
            _: Set[str] = find_dependencies(Arguments.from_args(args))

        assert sys_exit.value.code != os.EX_OK

    def test_local_compilation(self):
        output: str = "compilation_test"
        args: List[str] = ["g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp", f"-o{output}"]

        assert not Path(output).exists()
        assert compile_locally(Arguments.from_args(args), DEFAULT_LOCALHOST) == os.EX_OK
        assert Path(output).exists()

        executable_stdout: str = subprocess.check_output([f"./{output}"], encoding="utf-8")
        assert executable_stdout == "homcc\n"

        Path(output).unlink(missing_ok=True)

        # intentionally execute an erroneous call
        assert compile_locally(Arguments.from_args(args + ["-OError"]), DEFAULT_LOCALHOST) != os.EX_OK
