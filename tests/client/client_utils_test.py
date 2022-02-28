import os
import pytest

from datetime import datetime
from homcc.client.client_utils import *
from pathlib import Path


class TestClientUtils:
    # pylint: disable=W0201
    @pytest.fixture(autouse=True)
    def _init(self):
        self.example_base_dir: Path = Path("example")
        self.example_main_cpp: Path = self.example_base_dir / "src" / "main.cpp"
        self.example_foo_cpp: Path = self.example_base_dir / "src" / "foo.cpp"
        self.example_inc_dir: Path = self.example_base_dir / "include"

        self.example_out_dir: Path = self.example_base_dir / "build"
        self.example_out_dir.mkdir(exist_ok=True)

    def test_find_dependencies(self):
        assert self.example_main_cpp.exists()

        args: List[str] = ["g++", str(self.example_main_cpp.absolute()),
                           f"-I{str(self.example_inc_dir.absolute())}"]
        dependency_list: List[str] = find_dependencies(args)

        example_dep: Path = self.example_inc_dir / "foo.h"

        assert len(dependency_list) == 2
        assert dependency_list[0] == str(self.example_main_cpp.absolute())
        assert dependency_list[1] == str(example_dep.absolute())

    def test_local_compilation(self):
        time_str: str = datetime.now().strftime("%Y%m%d-%H%M%S")
        example_out_file: Path = self.example_out_dir / f"example-{time_str}"

        args: List[str] = ["g++", str(self.example_main_cpp.absolute()),
                           str(self.example_foo_cpp.absolute()),
                           f"-I{str(self.example_inc_dir.absolute())}",
                           "-o", str(example_out_file.absolute())]

        assert not example_out_file.exists()
        assert local_compile(args) == os.EX_OK
        assert example_out_file.exists()

        example_out_file.unlink()
