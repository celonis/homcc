""" Tests for client/client_utils.py"""
import pytest

import os

from datetime import datetime
from pathlib import Path
from typing import List, Set

from homcc.common.arguments import Arguments
from homcc.client.client_utils import (
    CompilerError,
    compile_locally,
    find_dependencies,
    # scan_includes,
)


class TestClientUtilsFunctions:
    """Tests for functions in client/client_utils.py"""

    @pytest.fixture(autouse=True)
    def _init(self):
        self.example_base_dir: Path = Path("example")
        self.example_main_cpp: Path = self.example_base_dir / "src" / "main.cpp"
        self.example_foo_cpp: Path = self.example_base_dir / "src" / "foo.cpp"
        self.example_inc_dir: Path = self.example_base_dir / "include"

        self.example_out_dir: Path = self.example_base_dir / "build"
        self.example_out_dir.mkdir(exist_ok=True)

    def test_scan_includes(self):
        pass  # TODO

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

        with pytest.raises(CompilerError):
            _: Set[str] = find_dependencies(Arguments.from_args(args))

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
