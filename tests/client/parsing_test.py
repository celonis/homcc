""" Tests for client/parsing.py"""
import pytest

import os
import subprocess

from pathlib import Path
from pytest import CaptureFixture
from pytest_mock.plugin import MockerFixture
from typing import List

from homcc.client.parsing import (
    HOMCC_CLIENT_CONFIG_FILENAME,
    HOMCC_HOSTS_ENV_VAR,
    HOMCC_HOSTS_FILENAME,
    ClientConfig,
    ConnectionType,
    Host,
    HostParsingError,
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
        assert len(cap.out.splitlines()) == len(self.mocked_hosts)
        for host in self.mocked_hosts:
            assert host in cap.out

    def test_show_concurrency_level(self, capfd: CaptureFixture):
        with pytest.raises(SystemExit) as sys_exit:
            parse_cli_args(["-j"])

        cap = capfd.readouterr()

        assert sys_exit.value.code == os.EX_OK
        assert not cap.err
        assert f"{8 + 64}\n" == cap.out

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
        failing_hosts: List[str] = ["", " ", "#", ",", "remotehost/-1"]

        for failing_host in failing_hosts:
            with pytest.raises(HostParsingError):
                _ = parse_host(failing_host)

    def test_parse_host_trailing_comment(self):
        # HOST#COMMENT
        assert parse_host("localhost#COMMENT") == Host(type=ConnectionType.TCP, host="localhost")
        assert parse_host("localhost/64#COMMENT") == Host(type=ConnectionType.TCP, host="localhost", limit="64")
        assert parse_host("localhost,lzo#COMMENT") == Host(type=ConnectionType.TCP, host="localhost", compression="lzo")
        assert parse_host("localhost/64,lzo#COMMENT") == Host(
            type=ConnectionType.TCP, host="localhost", limit="64", compression="lzo"
        )

    def test_host(self):
        tcp: ConnectionType = ConnectionType.TCP

        # HOST
        assert parse_host("localhost") == Host(type=tcp, host="localhost")
        assert parse_host("127.0.0.1") == Host(type=tcp, host="127.0.0.1")
        assert parse_host("::1") == Host(type=tcp, host="::1")

        # HOST/LIMIT
        assert parse_host("localhost/64") == Host(type=tcp, host="localhost", limit="64")
        assert parse_host("127.0.0.1/64") == Host(type=tcp, host="127.0.0.1", limit="64")
        assert parse_host("::1/64") == Host(type=tcp, host="::1", limit="64")

        # HOST,COMPRESSION
        assert parse_host("localhost,lzo") == Host(type=tcp, host="localhost", compression="lzo")
        assert parse_host("127.0.0.1,lzo") == Host(type=tcp, host="127.0.0.1", compression="lzo")
        assert parse_host("::1,lzo") == Host(type=tcp, host="::1", compression="lzo")

        # HOST/LIMIT,COMPRESSION
        assert parse_host("localhost/64,lzo") == Host(type=tcp, host="localhost", limit="64", compression="lzo")
        assert parse_host("127.0.0.1/64,lzo") == Host(type=tcp, host="127.0.0.1", limit="64", compression="lzo")
        assert parse_host("::1/64,lzo") == Host(type=tcp, host="::1", limit="64", compression="lzo")

    def test_host_port(self):
        tcp: ConnectionType = ConnectionType.TCP

        # HOST:PORT
        assert parse_host("localhost:3633") == Host(type=tcp, host="localhost", port="3633")
        assert parse_host("127.0.0.1:3633") == Host(type=tcp, host="127.0.0.1", port="3633")
        assert parse_host("[::1]:3633") == Host(type=tcp, host="::1", port="3633")

        # HOST:PORT/LIMIT
        assert parse_host("localhost:3633/64") == Host(type=tcp, host="localhost", limit="64", port="3633")
        assert parse_host("127.0.0.1:3633/64") == Host(type=tcp, host="127.0.0.1", limit="64", port="3633")
        assert parse_host("[::1]:3633/64") == Host(type=tcp, host="::1", limit="64", port="3633")

        # HOST:PORT,COMPRESSION
        assert parse_host("localhost:3633,lzo") == Host(type=tcp, host="localhost", compression="lzo", port="3633")
        assert parse_host("127.0.0.1:3633,lzo") == Host(type=tcp, host="127.0.0.1", compression="lzo", port="3633")
        assert parse_host("[::1]:3633,lzo") == Host(type=tcp, host="::1", compression="lzo", port="3633")

        # HOST:PORT/LIMIT,COMPRESSION
        assert parse_host("localhost:3633/64,lzo") == Host(
            type=tcp, host="localhost", limit="64", compression="lzo", port="3633"
        )
        assert parse_host("127.0.0.1:3633/64,lzo") == Host(
            type=tcp, host="127.0.0.1", limit="64", compression="lzo", port="3633"
        )
        assert parse_host("[::1]:3633/64,lzo") == Host(type=tcp, host="::1", limit="64", compression="lzo", port="3633")

    def test_at_host(self):
        ssh: ConnectionType = ConnectionType.SSH

        # @HOST
        assert parse_host("@localhost") == Host(type=ssh, host="localhost")
        assert parse_host("@127.0.0.1") == Host(type=ssh, host="127.0.0.1")
        assert parse_host("@::1") == Host(type=ssh, host="::1")

        # @HOST/LIMIT
        assert parse_host("@localhost/64") == Host(type=ssh, host="localhost", limit="64")
        assert parse_host("@127.0.0.1/64") == Host(type=ssh, host="127.0.0.1", limit="64")
        assert parse_host("@::1/64") == Host(type=ssh, host="::1", limit="64")

        # @HOST,COMPRESSION
        assert parse_host("@localhost,lzo") == Host(type=ssh, host="localhost", compression="lzo")
        assert parse_host("@127.0.0.1,lzo") == Host(type=ssh, host="127.0.0.1", compression="lzo")
        assert parse_host("@::1,lzo") == Host(type=ssh, host="::1", compression="lzo")

        # @HOST/LIMIT,COMPRESSION
        assert parse_host("@localhost/64,lzo") == Host(type=ssh, host="localhost", limit="64", compression="lzo")
        assert parse_host("@127.0.0.1/64,lzo") == Host(type=ssh, host="127.0.0.1", limit="64", compression="lzo")
        assert parse_host("@::1/64,lzo") == Host(type=ssh, host="::1", limit="64", compression="lzo")

    def test_user_at_host(self):
        ssh: ConnectionType = ConnectionType.SSH

        # USER@HOST
        assert parse_host("user@localhost") == Host(type=ssh, host="localhost", user="user")
        assert parse_host("user@127.0.0.1") == Host(type=ssh, host="127.0.0.1", user="user")
        assert parse_host("user@::1") == Host(type=ssh, host="::1", user="user")

        # USER@HOST/LIMIT
        assert parse_host("user@localhost/64") == Host(type=ssh, host="localhost", limit="64", user="user")
        assert parse_host("user@127.0.0.1/64") == Host(type=ssh, host="127.0.0.1", limit="64", user="user")
        assert parse_host("user@::1/64") == Host(type=ssh, host="::1", limit="64", user="user")

        # USER@HOST,COMPRESSION
        assert parse_host("user@localhost,lzo") == Host(type=ssh, host="localhost", compression="lzo", user="user")
        assert parse_host("user@127.0.0.1,lzo") == Host(type=ssh, host="127.0.0.1", compression="lzo", user="user")
        assert parse_host("user@::1,lzo") == Host(type=ssh, host="::1", compression="lzo", user="user")

        # USER@HOST/LIMIT,COMPRESSION
        assert parse_host("user@localhost/64,lzo") == Host(
            type=ssh, host="localhost", limit="64", compression="lzo", user="user"
        )
        assert parse_host("user@127.0.0.1/64,lzo") == Host(
            type=ssh, host="127.0.0.1", limit="64", compression="lzo", user="user"
        )
        assert parse_host("user@::1/64,lzo") == Host(type=ssh, host="::1", limit="64", compression="lzo", user="user")

    def test_load_hosts(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        hosts = ["localhost", "localhost:3633 ", "localhost:3633,lzo\t", " ", ""]
        hosts_no_whitespace = ["localhost", "localhost:3633", "localhost:3633,lzo"]

        # $HOMCC_HOSTS
        monkeypatch.setenv(HOMCC_HOSTS_ENV_VAR, "\n".join(hosts))
        assert load_hosts() == hosts_no_whitespace

        # HOSTS file
        tmp_hosts_file: Path = tmp_path / HOMCC_HOSTS_FILENAME
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
        "verbose=TRUE  # DEBUG",
        " TIMEOUT = 180 ",
        "\tCoMpReSsIoN=lzo",
    ]

    def test_parse_config(self):
        assert parse_config(self.config) == ClientConfig(
            compiler="g++", compression="lzo", verbose="True", timeout="180"
        )

    def test_parse_loaded_config_file(self, tmp_path: Path):
        tmp_config_file: Path = tmp_path / HOMCC_CLIENT_CONFIG_FILENAME
        tmp_config_file.write_text("\n".join(self.config))

        config_file_locations: List[Path] = [tmp_config_file]

        assert parse_config(load_config_file(config_file_locations)) == ClientConfig(
            compiler="g++", compression="lzo", verbose="True", timeout="180"
        )
