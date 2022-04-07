""" Tests for client/client_utils.py"""
import os
import sys

from datetime import datetime
from pathlib import Path
from typing import List, Set

import pytest

from homcc.common.arguments import Arguments
from homcc.client.client_utils import CompilerError, DestinationParser, find_dependencies, compile_locally


class TestClientUtilsDestinationParser:
    """Tests for client.client_utils.DestinationParser"""

    def test_host(self):
        # HOST
        localhost: str = "localhost"
        parser = DestinationParser(localhost)
        assert parser.is_tcp()
        assert not parser.is_ssh()
        assert parser["host"] == "localhost"
        assert parser["port"] is None
        assert parser["user"] is None
        assert parser["compression"] is None

        ipv4_host: str = "127.0.0.1"
        parser = DestinationParser(ipv4_host)
        assert parser.is_tcp()
        assert not parser.is_ssh()
        assert parser["host"] == "127.0.0.1"
        assert parser["port"] is None
        assert parser["user"] is None
        assert parser["compression"] is None

        # ipv6_host: str = "::1"
        # parser = DestinationParser(ipv6_host)
        # assert parser.is_tcp()
        # assert not parser.is_ssh()
        # assert parser["host"] == "::1"
        # assert parser["port"] is None
        # assert parser["user"] is None
        # assert parser["compression"] is None

        # HOST,COMPRESSION
        localhost_comp: str = "localhost,lzo"
        parser = DestinationParser(localhost_comp)
        assert parser.is_tcp()
        assert not parser.is_ssh()
        assert parser["host"] == "localhost"
        assert parser["port"] is None
        assert parser["user"] is None
        assert parser["compression"] == "lzo"

        ipv4_host_comp: str = "127.0.0.1,lzo"
        parser = DestinationParser(ipv4_host_comp)
        assert parser.is_tcp()
        assert not parser.is_ssh()
        assert parser["host"] == "127.0.0.1"
        assert parser["port"] is None
        assert parser["user"] is None
        assert parser["compression"] == "lzo"

        # ipv6_host_comp: str = "::1,lzo"
        # parser = DestinationParser(ipv6_host_comp)
        # assert parser.is_tcp()
        # assert not parser.is_ssh()
        # assert parser["host"] == "::1"
        # assert parser["port"] is None
        # assert parser["user"] is None
        # assert parser["compression"] == "lzo"

    def test_host_port(self):
        # HOST:PORT
        localhost_port: str = "localhost:3633"
        parser = DestinationParser(localhost_port)
        assert parser.is_tcp()
        assert not parser.is_ssh()
        assert parser["host"] == "localhost"
        assert parser["port"] == "3633"
        assert parser["user"] is None
        assert parser["compression"] is None

        ipv4host_port: str = "127.0.0.1:3633"
        parser = DestinationParser(ipv4host_port)
        assert parser.is_tcp()
        assert not parser.is_ssh()
        assert parser["host"] == "127.0.0.1"
        assert parser["port"] == "3633"
        assert parser["user"] is None
        assert parser["compression"] is None

        # HOST:PORT,COMPRESSION
        localhost_port_comp: str = "localhost:3633,lzo"
        parser = DestinationParser(localhost_port_comp)
        assert parser.is_tcp()
        assert not parser.is_ssh()
        assert parser["host"] == "localhost"
        assert parser["port"] == "3633"
        assert parser["user"] is None
        assert parser["compression"] == "lzo"

        ipv4host_port_comp: str = "127.0.0.1:3633,lzo"
        parser = DestinationParser(ipv4host_port_comp)
        assert parser.is_tcp()
        assert not parser.is_ssh()
        assert parser["host"] == "127.0.0.1"
        assert parser["port"] == "3633"
        assert parser["user"] is None
        assert parser["compression"] == "lzo"

    def test_at_host(self):
        # @HOST
        at_host: str = "@localhost"
        parser = DestinationParser(at_host)
        assert not parser.is_tcp()
        assert parser.is_ssh()
        assert parser["host"] == "localhost"
        assert parser["port"] is None
        assert parser["user"] is None
        assert parser["compression"] is None

        # @HOST,COMPRESSION
        at_host_comp: str = "@localhost,lzo"
        parser = DestinationParser(at_host_comp)
        assert not parser.is_tcp()
        assert parser.is_ssh()
        assert parser["host"] == "localhost"
        assert parser["port"] is None
        assert parser["user"] is None
        assert parser["compression"] == "lzo"

    def test_user_at_host(self):
        # USER@HOST
        user_at_host: str = "user@localhost"
        parser = DestinationParser(user_at_host)
        assert not parser.is_tcp()
        assert parser.is_ssh()
        assert parser["host"] == "localhost"
        assert parser["port"] is None
        assert parser["user"] == "user"
        assert parser["compression"] is None

        # USER@HOST,COMPRESSION
        user_at_host_comp: str = "user@localhost,lzo"
        parser = DestinationParser(user_at_host_comp)
        assert not parser.is_tcp()
        assert parser.is_ssh()
        assert parser["host"] == "localhost"
        assert parser["port"] is None
        assert parser["user"] == "user"
        assert parser["compression"] == "lzo"


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

    def test_parse_args(self):
        sys.argv[0] = "homcc_client.py"
        # optional_info_args: List[str] = ["-h", "-v", "--hosts", "-j", "--dependencies"]

        # sys.argv[1] = ["-h"]
        # _: Namespace = parse_args(["-h"])
        assert True

        # for optional_info_arg in optional_info_args:
        #    _: Namespace = parse_args([optional_info_arg])  # run every arg to ensure that no ArgumentError was raised

        # with pytest.raises(ArgumentError):
        #    parse_args(["foobar"])

        # compiler_args: List[str] = ["g++", "-Iexample/include", "example/src/*.cpp"]

    def test_find_dependencies_without_class_impl(self):
        # absolute paths of: "g++ main.cpp -Iinclude/"
        args: List[str] = ["g++", str(self.example_main_cpp.absolute()), f"-I{str(self.example_inc_dir.absolute())}"]
        dependencies: Set[str] = find_dependencies(Arguments(args))
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
        dependencies: Set[str] = find_dependencies(Arguments(args))
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
            _: Set[str] = find_dependencies(Arguments(args))

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
        assert compile_locally(Arguments(args)) == os.EX_OK
        assert example_out_file.exists()

        example_out_file.unlink()

        # intentionally execute an erroneous call
        assert compile_locally(Arguments(args + ["-OError"])) != os.EX_OK
