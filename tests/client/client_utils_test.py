""" Tests for client/client_utils.py"""
import pytest

import os

from datetime import datetime
from pathlib import Path
from typing import List, Set

from homcc.common.arguments import Arguments
from homcc.client.client_utils import (
    CompilerError,
    ConnectionType,
    compile_locally,
    find_dependencies,
    parse_args,
    parse_destination,
    show_dependencies,
)


class TestClientUtilsParseArgs:
    """Tests for client.client_utils.parse_args"""

    def test_parse_optional_info_args(self):
        # optional info args exit early and do not require compiler args
        optional_info_args: List[str] = ["-h", "--version", "--hosts", "-j"]

        for optional_info_arg in optional_info_args:
            with pytest.raises(SystemExit) as info_exit:
                _ = parse_args([optional_info_arg])
                # TODO: capture stdout and assert
            assert info_exit.type == SystemExit
            assert info_exit.value.code == os.EX_OK

    def test_parse_args_dependencies(self):
        compiler_args = ["g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp"]

        # dependency arg exits early and requires compiler args
        with pytest.raises(SystemExit) as dependencies_exit:
            _, compiler_arguments = parse_args(["--dependencies"] + compiler_args)
            assert compiler_arguments == Arguments(compiler_args)
            show_dependencies(compiler_arguments)  # sys.exit happens here
            # TODO: capture stdout and assert
        assert dependencies_exit.type == SystemExit
        assert dependencies_exit.value.code == os.EX_OK


class TestClientUtilsParseDestination:
    """Tests for client.client_utils.parse_destination"""

    def test_host(self):
        # HOST
        localhost: str = "localhost"
        parsed_destination_dict = parse_destination(localhost)
        assert parsed_destination_dict["type"] == ConnectionType.TCP
        assert parsed_destination_dict["host"] == "localhost"
        assert parsed_destination_dict["port"] is None
        assert parsed_destination_dict["user"] is None
        assert parsed_destination_dict["compression"] is None

        ipv4_host: str = "127.0.0.1"
        parsed_destination_dict = parse_destination(ipv4_host)
        assert parsed_destination_dict["type"] == ConnectionType.TCP
        assert parsed_destination_dict["host"] == "127.0.0.1"
        assert parsed_destination_dict["port"] is None
        assert parsed_destination_dict["user"] is None
        assert parsed_destination_dict["compression"] is None

        # ipv6_host: str = "::1"
        # parsed_destination_dict = parse_destination(ipv6_host)
        # assert parsed_destination_dict == parse_destination.TCP
        # assert not parsed_destination_dict == parse_destination.SSH
        # assert parsed_destination_dict["host"] == "::1"
        # assert parsed_destination_dict["port"] is None
        # assert parsed_destination_dict["user"] is None
        # assert parsed_destination_dict["compression"] is None

        # HOST,COMPRESSION
        localhost_comp: str = "localhost,lzo"
        parsed_destination_dict = parse_destination(localhost_comp)
        assert parsed_destination_dict["type"] == ConnectionType.TCP
        assert parsed_destination_dict["host"] == "localhost"
        assert parsed_destination_dict["port"] is None
        assert parsed_destination_dict["user"] is None
        assert parsed_destination_dict["compression"] == "lzo"

        ipv4_host_comp: str = "127.0.0.1,lzo"
        parsed_destination_dict = parse_destination(ipv4_host_comp)
        assert parsed_destination_dict["type"] == ConnectionType.TCP
        assert parsed_destination_dict["host"] == "127.0.0.1"
        assert parsed_destination_dict["port"] is None
        assert parsed_destination_dict["user"] is None
        assert parsed_destination_dict["compression"] == "lzo"

        # ipv6_host_comp: str = "::1,lzo"
        # parsed_destination_dict = parse_destination(ipv6_host_comp)
        # assert parsed_destination_dict == parse_destination.TCP
        # assert not parsed_destination_dict == parse_destination.SSH
        # assert parsed_destination_dict["host"] == "::1"
        # assert parsed_destination_dict["port"] is None
        # assert parsed_destination_dict["user"] is None
        # assert parsed_destination_dict["compression"] == "lzo"

    def test_host_port(self):
        # HOST:PORT
        localhost_port: str = "localhost:3633"
        parsed_destination_dict = parse_destination(localhost_port)
        assert parsed_destination_dict["type"] == ConnectionType.TCP
        assert parsed_destination_dict["host"] == "localhost"
        assert parsed_destination_dict["port"] == "3633"
        assert parsed_destination_dict["user"] is None
        assert parsed_destination_dict["compression"] is None

        ipv4host_port: str = "127.0.0.1:3633"
        parsed_destination_dict = parse_destination(ipv4host_port)
        assert parsed_destination_dict["type"] == ConnectionType.TCP
        assert parsed_destination_dict["host"] == "127.0.0.1"
        assert parsed_destination_dict["port"] == "3633"
        assert parsed_destination_dict["user"] is None
        assert parsed_destination_dict["compression"] is None

        # HOST:PORT,COMPRESSION
        localhost_port_comp: str = "localhost:3633,lzo"
        parsed_destination_dict = parse_destination(localhost_port_comp)
        assert parsed_destination_dict["type"] == ConnectionType.TCP
        assert parsed_destination_dict["host"] == "localhost"
        assert parsed_destination_dict["port"] == "3633"
        assert parsed_destination_dict["user"] is None
        assert parsed_destination_dict["compression"] == "lzo"

        ipv4host_port_comp: str = "127.0.0.1:3633,lzo"
        parsed_destination_dict = parse_destination(ipv4host_port_comp)
        assert parsed_destination_dict["type"] == ConnectionType.TCP
        assert parsed_destination_dict["host"] == "127.0.0.1"
        assert parsed_destination_dict["port"] == "3633"
        assert parsed_destination_dict["user"] is None
        assert parsed_destination_dict["compression"] == "lzo"

    def test_at_host(self):
        # @HOST
        at_host: str = "@host"
        parsed_destination_dict = parse_destination(at_host)
        assert parsed_destination_dict["type"] == ConnectionType.SSH
        assert parsed_destination_dict["host"] == "host"
        assert parsed_destination_dict["port"] is None
        assert parsed_destination_dict["user"] is None
        assert parsed_destination_dict["compression"] is None

        # @HOST,COMPRESSION
        at_host_comp: str = "@host,lzo"
        parsed_destination_dict = parse_destination(at_host_comp)
        assert parsed_destination_dict["type"] == ConnectionType.SSH
        assert parsed_destination_dict["host"] == "host"
        assert parsed_destination_dict["port"] is None
        assert parsed_destination_dict["user"] is None
        assert parsed_destination_dict["compression"] == "lzo"

    def test_user_at_host(self):
        # USER@HOST
        user_at_host: str = "user@host"
        parsed_destination_dict = parse_destination(user_at_host)
        assert parsed_destination_dict["type"] == ConnectionType.SSH
        assert parsed_destination_dict["host"] == "host"
        assert parsed_destination_dict["port"] is None
        assert parsed_destination_dict["user"] == "user"
        assert parsed_destination_dict["compression"] is None

        # USER@HOST,COMPRESSION
        user_at_host_comp: str = "user@host,lzo"
        parsed_destination_dict = parse_destination(user_at_host_comp)
        assert parsed_destination_dict["type"] == ConnectionType.SSH
        assert parsed_destination_dict["host"] == "host"
        assert parsed_destination_dict["port"] is None
        assert parsed_destination_dict["user"] == "user"
        assert parsed_destination_dict["compression"] == "lzo"


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
