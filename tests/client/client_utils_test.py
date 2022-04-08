""" Tests for client/client_utils.py"""
import pytest

import os

from datetime import datetime
from pathlib import Path
from typing import List, Set

from homcc.common.arguments import Arguments
from homcc.client.client_utils import (
    HOMCC_DIR_ENV_VAR,
    HOMCC_HOSTS_ENV_VAR,
    CompilerError,
    ConnectionType,
    compile_locally,
    find_dependencies,
    load_hosts,
    parse_args,
    parse_host,
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


class TestClientUtilsParseHost:
    """
    Tests for client.client_utils.parse_host

    Note: We currently only test for passing host formats for categorization, since more meaningful failing will usually
    occur later on when the client tries to connect to the specified host
    """

    def test_host(self):
        # HOST
        named_host: str = "localhost"
        parsed_host_dict = parse_host(named_host)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") is None

        ipv4_host: str = "127.0.0.1"
        parsed_host_dict = parse_host(ipv4_host)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") is None

        ipv6_host: str = "::1"
        parsed_host_dict = parse_host(ipv6_host)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") is None

        # HOST,COMPRESSION
        named_host_comp: str = "localhost,lzo"
        parsed_host_dict = parse_host(named_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") == "lzo"

        ipv4_host_comp: str = "127.0.0.1,lzo"
        parsed_host_dict = parse_host(ipv4_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") == "lzo"

        ipv6_host_comp: str = "::1,lzo"
        parsed_host_dict = parse_host(ipv6_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") == "lzo"

    def test_host_port(self):
        # HOST:PORT
        named_host_port: str = "localhost:3633"
        parsed_host_dict = parse_host(named_host_port)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") is None

        ipv4_host_port: str = "127.0.0.1:3633"
        parsed_host_dict = parse_host(ipv4_host_port)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") is None

        ipv6_host_port: str = "[::1]:3633"
        parsed_host_dict = parse_host(ipv6_host_port)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") is None

        # HOST:PORT,COMPRESSION
        named_host_port_comp: str = "localhost:3633,lzo"
        parsed_host_dict = parse_host(named_host_port_comp)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") == "lzo"

        ipv4_host_port_comp: str = "127.0.0.1:3633,lzo"
        parsed_host_dict = parse_host(ipv4_host_port_comp)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") == "lzo"

        ipv6_host_port_comp: str = "[::1]:3633,lzo"
        parsed_host_dict = parse_host(ipv6_host_port_comp)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") == "lzo"

    def test_at_host(self):
        # @HOST
        at_named_host: str = "@localhost"
        parsed_host_dict = parse_host(at_named_host)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") is None

        at_ipv4_host: str = "@127.0.0.1"
        parsed_host_dict = parse_host(at_ipv4_host)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") is None

        at_ipv6_host: str = "@::1"
        parsed_host_dict = parse_host(at_ipv6_host)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") is None

        # @HOST,COMPRESSION
        at_named_host_comp: str = "@localhost,lzo"
        parsed_host_dict = parse_host(at_named_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") == "lzo"

        at_ipv4_host_comp: str = "@127.0.0.1,lzo"
        parsed_host_dict = parse_host(at_ipv4_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") == "lzo"

        at_ipv6_host_comp: str = "@::1,lzo"
        parsed_host_dict = parse_host(at_ipv6_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("compression") == "lzo"

    def test_user_at_host(self):
        # USER@HOST
        user_at_named_host: str = "user@localhost"
        parsed_host_dict = parse_host(user_at_named_host)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") == "user"
        assert parsed_host_dict.get("compression") is None

        user_at_ipv4_host: str = "user@127.0.0.1"
        parsed_host_dict = parse_host(user_at_ipv4_host)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") == "user"
        assert parsed_host_dict.get("compression") is None

        user_at_ipv6_host: str = "user@::1"
        parsed_host_dict = parse_host(user_at_ipv6_host)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") == "user"
        assert parsed_host_dict.get("compression") is None

        # USER@HOST,COMPRESSION
        user_at_named_host_comp: str = "user@localhost,lzo"
        parsed_host_dict = parse_host(user_at_named_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") == "user"
        assert parsed_host_dict.get("compression") == "lzo"

        user_at_ipv4_host_comp: str = "user@127.0.0.1,lzo"
        parsed_host_dict = parse_host(user_at_ipv4_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") == "user"
        assert parsed_host_dict.get("compression") == "lzo"

        user_at_ipv6_host_comp: str = "user@::1,lzo"
        parsed_host_dict = parse_host(user_at_ipv6_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") == "user"
        assert parsed_host_dict.get("compression") == "lzo"


class TestClientUtilsLoadHosts:
    """Tests for client.client_utils.load_hosts"""

    def test_load_hosts(self, monkeypatch):
        hosts = ["localhost", "localhost:3633 ", "localhost:3633,lzo\t", " ", ""]
        hosts_no_whitespace = ["localhost", "localhost:3633", "localhost:3633,lzo"]

        # $HOMCC_HOSTS
        monkeypatch.setenv(HOMCC_HOSTS_ENV_VAR, "\n".join(hosts))
        assert load_hosts() == hosts_no_whitespace

        # $HOMCC_DIR/hosts
        assert HOMCC_DIR_ENV_VAR


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
