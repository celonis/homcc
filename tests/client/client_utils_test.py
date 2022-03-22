""" Tests for client/client_utils.py"""
import os

from datetime import datetime
from pathlib import Path
from typing import List, Set

import pytest

from homcc.common.arguments import Arguments
from homcc.client.client_utils import find_dependencies, local_compile


# pylint: disable=missing-function-docstring
class TestClientUtils:
    """ Tests for client/client_utils.py"""

    # pylint: disable=W0201
    @pytest.fixture(autouse=True)
    def _init(self):
        self.example_base_dir: Path = Path("example")
        self.example_main_cpp: Path = self.example_base_dir / "src" / "main.cpp"
        self.example_foo_cpp: Path = self.example_base_dir / "src" / "foo.cpp"
        self.example_inc_dir: Path = self.example_base_dir / "include"

        self.example_out_dir: Path = self.example_base_dir / "build"
        self.example_out_dir.mkdir(exist_ok=True)

    def test_find_dependencies_without_class_impl(self):
        # absolute paths of: "g++ main.cpp -Iinclude/"
        args: List[str] = ["g++", str(self.example_main_cpp.absolute()),
                           f"-I{str(self.example_inc_dir.absolute())}"]
        dependencies: Set[str] = find_dependencies(Arguments(args))
        example_dependency: Path = self.example_inc_dir / "foo.h"

        assert len(dependencies) == 2
        assert str(self.example_main_cpp.absolute()) in dependencies
        assert str(example_dependency.absolute()) in dependencies

    def test_find_dependencies_with_class_impl(self):
        # absolute paths of: "g++ main.cpp foo.cpp -Iinclude/"
        args: List[str] = ["g++", str(self.example_main_cpp.absolute()),
                           str(self.example_foo_cpp.absolute()),
                           f"-I{str(self.example_inc_dir.absolute())}"]
        dependencies: Set[str] = find_dependencies(Arguments(args))
        example_dependency: Path = self.example_inc_dir / "foo.h"

        assert len(dependencies) == 3
        assert str(self.example_main_cpp.absolute()) in dependencies
        assert str(self.example_foo_cpp.absolute()) in dependencies
        assert str(example_dependency.absolute()) in dependencies

    def test_local_compilation(self):
        time_str: str = datetime.now().strftime("%Y%m%d-%H%M%S")
        example_out_file: Path = self.example_out_dir / f"example-{time_str}"

        # absolute paths of: "g++ main.cpp foo.cpp -Iinclude/ -o example-YYYYmmdd-HHMMSS"
        args: List[str] = ["g++", str(self.example_main_cpp.absolute()),
                           str(self.example_foo_cpp.absolute()),
                           f"-I{str(self.example_inc_dir.absolute())}",
                           "-o", str(example_out_file.absolute())]

        assert not example_out_file.exists()
        assert local_compile(Arguments(args)) == os.EX_OK
        assert example_out_file.exists()

        example_out_file.unlink()
