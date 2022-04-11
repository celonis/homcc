""" Tests for client/client_utils.py"""
import pytest

import os

from typing import List

from homcc.common.arguments import Arguments
from homcc.client.parsing import (
    HOMCC_DIR_ENV_VAR,
    HOMCC_HOSTS_ENV_VAR,
    ConnectionType,
    load_hosts,
    parse_cli_args,
    parse_host,
    parse_config,
)
from homcc.client.client_utils import scan_includes


class TestParsingCLIArgs:
    """Tests for client.client_utils.parse_args"""

    def test_parse_optional_info_args(self):
        # optional info args exit early and do not require compiler args
        optional_info_args: List[str] = ["--help", "--version", "--hosts", "-j"]

        for optional_info_arg in optional_info_args:
            with pytest.raises(SystemExit) as info_exit:
                _ = parse_cli_args([optional_info_arg])
                # TODO: capture stdout and assert
            assert info_exit.type == SystemExit
            assert info_exit.value.code == os.EX_OK

    def test_parse_args_scan_includes(self):
        compiler_args = ["g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp"]

        # dependency arg exits early and requires compiler args
        _, compiler_arguments = parse_cli_args(["--scan-includes"] + compiler_args)
        assert compiler_arguments == Arguments.from_args(compiler_args)
        assert scan_includes(compiler_arguments) == os.EX_OK


class TestParsingHosts:
    """
    Tests for client.parsing related to hosts files

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

    def test_load_hosts(self, monkeypatch):
        hosts = ["localhost", "localhost:3633 ", "localhost:3633,lzo\t", " ", ""]
        hosts_no_whitespace = ["localhost", "localhost:3633", "localhost:3633,lzo"]

        # $HOMCC_HOSTS
        monkeypatch.setenv(HOMCC_HOSTS_ENV_VAR, "\n".join(hosts))
        assert load_hosts() == hosts_no_whitespace

        # $HOMCC_DIR/hosts
        assert HOMCC_DIR_ENV_VAR


class TestParsingConfig:
    """
    Tests for client.parsing related to config files
    """

    def test_parse_config(self):
        config: List[str] = [
            "",
            " ",
            "# HOMCC TEST CONFIG",
            "COMPILER=g++",
            "DEBUG=TRUE  # DEBUG",
            " TIMEOUT = 180 ",
            "\tCoMpReSsIoN=lZo",
        ]
        parsed_config = parse_config("\n".join(config))

        assert parsed_config["COMPILER"] == "g++"
        assert parsed_config["DEBUG"] == "true"
        assert parsed_config["TIMEOUT"] == "180"
        assert parsed_config["COMPRESSION"] == "lzo"
