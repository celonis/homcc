""" Tests for client/parsing.py"""
import pytest

import os
import subprocess

from pathlib import Path
from pytest import CaptureFixture
from pytest_mock.plugin import MockerFixture
from typing import Dict, List

from homcc.client.parsing import (
    HOMCC_HOSTS_ENV_VAR,
    ConnectionType,
    parse_cli_args,
    load_config_file,
    load_hosts,
    parse_host,
    parse_config,
)


class TestCLI:
    """Tests for client.parsing.parse_cli_args"""

    mocked_hosts: List[str] = ["localhost/8", "remotehost/64"]

    @pytest.fixture(autouse=True)
    def setup_mock(self, mocker: MockerFixture):
        mocker.patch(
            "homcc.client.parsing.load_hosts",
            return_value=self.mocked_hosts,
        )

    def test_version(self, capfd: CaptureFixture):
        with pytest.raises(SystemExit) as sys_exit:
            parse_cli_args(["--version"])

        cap = capfd.readouterr()

        assert sys_exit.value.code == os.EX_OK
        assert not cap.err
        assert "homcc 0.0.1" in cap.out

    def test_show_hosts(self, capfd: CaptureFixture):
        with pytest.raises(SystemExit) as sys_exit:
            parse_cli_args(["--show-hosts"])

        cap = capfd.readouterr()

        assert sys_exit.value.code == os.EX_OK
        assert not cap.err
        for host in self.mocked_hosts:
            assert host in cap.out

    def test_show_concurrency_level(self, capfd: CaptureFixture):
        with pytest.raises(SystemExit) as sys_exit:
            parse_cli_args(["-j"])

        cap = capfd.readouterr()

        assert sys_exit.value.code == os.EX_OK
        assert not cap.err
        assert str(8 + 64) in cap.out

    def test_scan_includes(self):
        compiler_args: List[str] = ["g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp"]
        homcc_args = ["homcc/client/main.py", "--scan-includes"] + compiler_args

        result = subprocess.run(
            homcc_args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

        assert result.returncode == os.EX_OK
        assert "example/include/foo.h" in result.stdout


class TestParsingHosts:
    """
    Tests for parsing related to hosts files

    Note: We currently mostly test for passing host formats for categorization, since more meaningful failing will
    usually occur later on when the client tries to connect to the specified host
    """

    def test_parse_host_failing(self):
        failing_hosts: List[str] = ["", " ", "#", ","]

        for failing_host in failing_hosts:
            with pytest.raises(ValueError):
                _ = parse_host(failing_host)

    def test_parse_host_trailing_comment(self):
        # HOST#COMMENT
        named_host: str = "localhost#COMMENT"
        parsed_host_dict = parse_host(named_host)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") is None
        assert parsed_host_dict.get("compression") is None

    def test_host(self):
        # HOST
        named_host: str = "localhost/64"
        parsed_host_dict = parse_host(named_host)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") is None

        ipv4_host: str = "127.0.0.1/64"
        parsed_host_dict = parse_host(ipv4_host)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") is None

        ipv6_host: str = "::1/64"
        parsed_host_dict = parse_host(ipv6_host)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") is None

        # HOST,COMPRESSION
        named_host_comp: str = "localhost/64,lzo"
        parsed_host_dict = parse_host(named_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") == "lzo"

        ipv4_host_comp: str = "127.0.0.1/64,lzo"
        parsed_host_dict = parse_host(ipv4_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") == "lzo"

        ipv6_host_comp: str = "::1/64,lzo"
        parsed_host_dict = parse_host(ipv6_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") == "lzo"

    def test_host_port(self):
        # HOST:PORT
        named_host_port: str = "localhost:3633"
        parsed_host_dict = parse_host(named_host_port)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") is None
        assert parsed_host_dict.get("compression") is None

        ipv4_host_port: str = "127.0.0.1:3633"
        parsed_host_dict = parse_host(ipv4_host_port)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") is None
        assert parsed_host_dict.get("compression") is None

        ipv6_host_port: str = "[::1]:3633"
        parsed_host_dict = parse_host(ipv6_host_port)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") is None
        assert parsed_host_dict.get("compression") is None

        # HOST:PORT,COMPRESSION
        named_host_port_comp: str = "localhost:3633,lzo"
        parsed_host_dict = parse_host(named_host_port_comp)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") is None
        assert parsed_host_dict.get("compression") == "lzo"

        ipv4_host_port_comp: str = "127.0.0.1:3633,lzo"
        parsed_host_dict = parse_host(ipv4_host_port_comp)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") is None
        assert parsed_host_dict.get("compression") == "lzo"

        ipv6_host_port_comp: str = "[::1]:3633,lzo"
        parsed_host_dict = parse_host(ipv6_host_port_comp)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") is None
        assert parsed_host_dict.get("compression") == "lzo"

        # HOST:PORT/LIMIT
        named_host_port_limit: str = "localhost:3633/64"
        parsed_host_dict = parse_host(named_host_port_limit)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") is None

        ipv4_host_port_limit: str = "127.0.0.1:3633/64"
        parsed_host_dict = parse_host(ipv4_host_port_limit)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") is None

        ipv6_host_port_limit: str = "[::1]:3633/64"
        parsed_host_dict = parse_host(ipv6_host_port_limit)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") is None

        # HOST:PORT/LIMIT,COMPRESSION
        named_host_port_comp_limit: str = "localhost:3633/64,lzo"
        parsed_host_dict = parse_host(named_host_port_comp_limit)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") == "lzo"

        ipv4_host_port_comp_limit: str = "127.0.0.1:3633/64,lzo"
        parsed_host_dict = parse_host(ipv4_host_port_comp_limit)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") == "lzo"

        ipv6_host_port_comp_limit: str = "[::1]:3633/64,lzo"
        parsed_host_dict = parse_host(ipv6_host_port_comp_limit)
        assert parsed_host_dict.get("type") == ConnectionType.TCP
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") == "3633"
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") == "lzo"

    def test_at_host(self):
        # @HOST
        at_named_host: str = "@localhost/64"
        parsed_host_dict = parse_host(at_named_host)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") is None

        at_ipv4_host: str = "@127.0.0.1/64"
        parsed_host_dict = parse_host(at_ipv4_host)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") is None

        at_ipv6_host: str = "@::1/64"
        parsed_host_dict = parse_host(at_ipv6_host)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") is None

        # @HOST,COMPRESSION
        at_named_host_comp: str = "@localhost/64,lzo"
        parsed_host_dict = parse_host(at_named_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") == "lzo"

        at_ipv4_host_comp: str = "@127.0.0.1/64,lzo"
        parsed_host_dict = parse_host(at_ipv4_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") == "lzo"

        at_ipv6_host_comp: str = "@::1/64,lzo"
        parsed_host_dict = parse_host(at_ipv6_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") is None
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") == "lzo"

    def test_user_at_host(self):
        # USER@HOST
        user_at_named_host: str = "user@localhost/64"
        parsed_host_dict = parse_host(user_at_named_host)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") == "user"
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") is None

        user_at_ipv4_host: str = "user@127.0.0.1/64"
        parsed_host_dict = parse_host(user_at_ipv4_host)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") == "user"
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") is None

        user_at_ipv6_host: str = "user@::1/64"
        parsed_host_dict = parse_host(user_at_ipv6_host)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") == "user"
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") is None

        # USER@HOST,COMPRESSION
        user_at_named_host_comp: str = "user@localhost/64,lzo"
        parsed_host_dict = parse_host(user_at_named_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "localhost"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") == "user"
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") == "lzo"

        user_at_ipv4_host_comp: str = "user@127.0.0.1/64,lzo"
        parsed_host_dict = parse_host(user_at_ipv4_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "127.0.0.1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") == "user"
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") == "lzo"

        user_at_ipv6_host_comp: str = "user@::1/64,lzo"
        parsed_host_dict = parse_host(user_at_ipv6_host_comp)
        assert parsed_host_dict.get("type") == ConnectionType.SSH
        assert parsed_host_dict.get("host") == "::1"
        assert parsed_host_dict.get("port") is None
        assert parsed_host_dict.get("user") == "user"
        assert parsed_host_dict.get("limit") == "64"
        assert parsed_host_dict.get("compression") == "lzo"

    def test_load_hosts(self, monkeypatch, tmp_path):
        hosts = ["localhost", "localhost:3633 ", "localhost:3633,lzo\t", " ", ""]
        hosts_no_whitespace = ["localhost", "localhost:3633", "localhost:3633,lzo"]

        # $HOMCC_HOSTS
        monkeypatch.setenv(HOMCC_HOSTS_ENV_VAR, "\n".join(hosts))
        assert load_hosts() == hosts_no_whitespace

        # HOSTS file
        tmp_hosts_file: Path = tmp_path / "config"
        tmp_hosts_file.write_text("\n".join(hosts))

        hosts_file_locations: List[Path] = [tmp_hosts_file]

        assert load_hosts(hosts_file_locations) == hosts_no_whitespace


class TestParsingConfig:
    """
    Tests for client.parsing related to config files
    """

    config: List[str] = [
        "",
        " ",
        "# HOMCC TEST CONFIG COMMENT",
        " # comment with whitespace ",
        "COMPILER=g++",
        "DEBUG=TRUE  # DEBUG",
        " TIMEOUT = 180 ",
        "\tCoMpReSsIoN=lZo",
    ]

    def test_parse_config(self):
        parsed_config = parse_config("\n".join(self.config))

        assert parsed_config["COMPILER"] == "g++"
        assert parsed_config["DEBUG"] == "true"
        assert parsed_config["TIMEOUT"] == "180"
        assert parsed_config["COMPRESSION"] == "lzo"

    def test_load_config_file(self, tmp_path):
        tmp_config_file: Path = tmp_path / "config"
        tmp_config_file.write_text("\n".join(self.config))

        config_file_locations: List[Path] = [tmp_config_file]

        parsed_config: Dict[str, str] = load_config_file(config_file_locations)

        assert parsed_config["COMPILER"] == "g++"
        assert parsed_config["DEBUG"] == "true"
        assert parsed_config["TIMEOUT"] == "180"
        assert parsed_config["COMPRESSION"] == "lzo"
