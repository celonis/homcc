""" Tests for client/compilation.py"""
import pytest

import os

from datetime import datetime
from pathlib import Path
from typing import List, Set

from homcc.common.arguments import Arguments
from homcc.client.compilation import (
    compile_locally,
    find_dependencies,
    scan_includes,
)


class TestCompilation:
    """Tests for functions in client/compilation.py"""

    @pytest.fixture(autouse=True)
    def _init(self):
        self.example_base_dir: Path = Path("example")
        self.example_main_cpp: Path = self.example_base_dir / "src" / "main.cpp"
        self.example_foo_cpp: Path = self.example_base_dir / "src" / "foo.cpp"
        self.example_inc_dir: Path = self.example_base_dir / "include"

        self.example_out_dir: Path = self.example_base_dir / "build"
        self.example_out_dir.mkdir(exist_ok=True)

    def test_scan_includes(self):
        arguments: Arguments = Arguments.from_args(
            ["g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp"]
        )

        includes: List[str] = scan_includes(arguments)

        assert len(includes) == 1
        assert "example/include/foo.h" in includes

    def test_find_dependencies_without_class_impl(self):
        # absolute paths of: "g++ main.cpp -Iinclude/"
        args: List[str] = ["g++", str(self.example_main_cpp.absolute()), f"-I{str(self.example_inc_dir.absolute())}"]
        dependencies: Set[str] = find_dependencies(Arguments.from_args(args))
        example_dependency: Path = self.example_inc_dir / "foo.h"

        assert len(dependencies) == 2
        assert str(self.example_main_cpp.absolute()) in dependencies
        assert str(example_dependency.absolute()) in dependencies

    def test_find_dependencies_with_class_impl(self):
        # absolute paths of: "g++ main.cpp foo.cpp -Iinclude/"
        args: List[str] = [
            "g++",
            str(self.example_main_cpp.absolute()),
            str(self.example_foo_cpp.absolute()),
            f"-I{str(self.example_inc_dir.absolute())}",
        ]
        dependencies: Set[str] = find_dependencies(Arguments.from_args(args))
        example_dependency: Path = self.example_inc_dir / "foo.h"

        assert len(dependencies) == 3
        assert str(self.example_main_cpp.absolute()) in dependencies
        assert str(self.example_foo_cpp.absolute()) in dependencies
        assert str(example_dependency.absolute()) in dependencies

    def test_find_dependencies_error(self):
        args: List[str] = [
            "g++",
            str(self.example_main_cpp.absolute()),
            str(self.example_foo_cpp.absolute()),
            f"-I{str(self.example_inc_dir.absolute())}",
            "-OError",
        ]

        with pytest.raises(SystemExit) as sys_exit:
            _: Set[str] = find_dependencies(Arguments.from_args(args))

        assert sys_exit.value.code == 1

    def test_local_compilation(self):
        time_str: str = datetime.now().strftime("%Y%m%d-%H%M%S")
        example_out_file: Path = self.example_out_dir / f"example-{time_str}"

        # absolute paths of: "g++ main.cpp foo.cpp -Iinclude/ -o example-YYYYmmdd-HHMMSS"
        args: List[str] = [
            "g++",
            str(self.example_main_cpp.absolute()),
            str(self.example_foo_cpp.absolute()),
            f"-I{str(self.example_inc_dir.absolute())}",
            "-o",
            str(example_out_file.absolute()),
        ]

        assert not example_out_file.exists()
        assert compile_locally(Arguments.from_args(args)) == os.EX_OK
        assert example_out_file.exists()

        example_out_file.unlink()

        # intentionally execute an erroneous call
        assert compile_locally(Arguments.from_args(args + ["-OError"])) != os.EX_OK
