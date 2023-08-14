# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

""" Tests for client/compilation.py"""
import os
import subprocess
from pathlib import Path
from typing import List, Set

import pytest

from homcc.client.compilation import compile_locally, find_dependencies, scan_includes
from homcc.client.parsing import Host
from homcc.common.arguments import Arguments
from homcc.common.constants import ENCODING


class TestCompilation:
    """Tests for functions in client/compilation.py"""

    def test_scan_includes(self):
        arguments: Arguments = Arguments.from_vargs(
            "g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp"
        )

        includes: List[str] = scan_includes(arguments)

        assert len(includes) == 1
        assert str(Path("example/include/foo.h").absolute()) in includes

    @staticmethod
    def find_dependencies(compiler: str):
        args: List[str] = [compiler, "-Iexample/include", "example/src/main.cpp"]
        dependencies: Set[str] = find_dependencies(Arguments.from_vargs(*args))

        assert len(dependencies) == 2
        assert str(Path("example/src/main.cpp").absolute()) in dependencies
        assert str(Path("example/include/foo.h").absolute()) in dependencies

    @pytest.mark.gplusplus
    def test_find_dependencies_gplusplus(self):
        self.find_dependencies("g++")

    @pytest.mark.clangplusplus
    def test_find_dependencies_clangplusplus(self):
        self.find_dependencies("clang++")

    @staticmethod
    def find_dependencies_with_side_effects(compiler: str, tmp_path: Path):
        args: List[str] = [
            compiler,
            "-Iexample/include",
            "-MD",
            "-MT",
            "example/src/main.cpp.o",
            "-MF",
            f"{tmp_path}/main.cpp.o.d",
            "-o",
            f"{tmp_path}/main.cpp.o",
            "-c",
            "example/src/main.cpp",
        ]
        dependencies: Set[str] = find_dependencies(Arguments.from_vargs(*args))

        assert len(dependencies) == 2
        assert str(Path("example/src/main.cpp").absolute()) in dependencies
        assert str(Path("example/include/foo.h").absolute()) in dependencies

        assert Path(f"{tmp_path}/main.cpp.o.d").exists()
        assert Path(f"{tmp_path}/main.cpp.o").exists()

    @pytest.mark.gplusplus
    def test_find_dependencies_with_side_effects_gplusplus(self, tmp_path: Path):
        self.find_dependencies_with_side_effects("g++", tmp_path)

    @pytest.mark.clangplusplus
    def test_find_dependencies_with_side_effects_clangplusplus(self, tmp_path: Path):
        self.find_dependencies_with_side_effects("clang++", tmp_path)

    @staticmethod
    def find_dependencies_class_impl_with_compiler(compiler: str):
        dependencies: Set[str] = find_dependencies(
            Arguments.from_vargs(compiler, "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp")
        )

        assert len(dependencies) == 3
        assert str(Path("example/src/main.cpp").absolute()) in dependencies
        assert str(Path("example/src/foo.cpp").absolute()) in dependencies
        assert str(Path("example/include/foo.h").absolute()) in dependencies

    @pytest.mark.gplusplus
    def find_dependencies_with_class_impl_gplusplus(self):
        self.find_dependencies_class_impl_with_compiler("g++")

    @pytest.mark.clangplusplus
    def find_dependencies_with_class_impl_clangplusplus(self):
        self.find_dependencies_class_impl_with_compiler("clang++")

    def test_find_dependencies_error(self):
        with pytest.raises(subprocess.CalledProcessError):
            _: Set[str] = find_dependencies(
                Arguments.from_vargs(
                    "g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp", "-OError"
                )
            )

    def test_local_compilation(self):
        output: str = "compilation_test"
        args: List[str] = ["g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp", f"-o{output}"]

        assert not Path(output).exists()
        assert compile_locally(Arguments.from_vargs(*args), Host.localhost_with_limit(1)) == os.EX_OK
        assert Path(output).exists()

        executable_stdout: str = subprocess.check_output([f"./{output}"], encoding=ENCODING)
        assert executable_stdout == "homcc\n"

        Path(output).unlink(missing_ok=True)

        assert compile_locally(Arguments.from_vargs(*args, "-OError"), Host.localhost_with_limit(1)) != os.EX_OK
