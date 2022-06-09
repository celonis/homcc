""" Tests for client/parsing.py"""
import pytest

import os
import subprocess

from pathlib import Path
from pytest import CaptureFixture
from pytest_mock.plugin import MockerFixture
from typing import List

from homcc.client.errors import HostParsingError
from homcc.client.parsing import (
    HOMCC_HOSTS_ENV_VAR,
    HOMCC_HOSTS_FILENAME,
    ClientConfig,
    ConnectionType,
    Host,
    parse_cli_args,
    load_hosts,
    parse_host,
    parse_config,
)
from homcc.common.parsing import HOMCC_CONFIG_FILENAME


class TestCLI:
    """Tests for client.parsing.parse_cli_args"""

    MOCKED_HOSTS: List[str] = ["localhost/8", "remotehost/64"]

    @pytest.fixture(autouse=True)
    def setup_mock(self, mocker: MockerFixture):
        mocker.patch(
            "homcc.client.parsing.load_hosts",
            return_value=self.MOCKED_HOSTS,
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
        assert len(cap.out.splitlines()) == len(self.MOCKED_HOSTS)
        for host in self.MOCKED_HOSTS:
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
        failing_hosts: List[str] = [
            "",
            " ",
            "#",
            ",",
            "remotehost/-1",
            "remotehost:3633/-1",
            "@remotehost/-1",
            "user@remotehost/-1",
        ]

        for failing_host in failing_hosts:
            with pytest.raises(HostParsingError):
                _ = parse_host(failing_host)

    def test_parse_host_trailing_comment(self):
        # HOST#COMMENT
        assert parse_host("localhost#COMMENT") == Host(type=ConnectionType.LOCAL, host="localhost")
        assert parse_host("localhost/64#COMMENT") == Host(type=ConnectionType.LOCAL, host="localhost", limit="64")
        assert parse_host("localhost,lzo#COMMENT") == Host(
            type=ConnectionType.LOCAL, host="localhost", compression="lzo"
        )
        assert parse_host("localhost/64,lzo#COMMENT") == Host(
            type=ConnectionType.LOCAL, host="localhost", limit="64", compression="lzo"
        )

    def test_host(self):
        local: ConnectionType = ConnectionType.LOCAL
        tcp: ConnectionType = ConnectionType.TCP

        # HOST
        assert parse_host("localhost") == Host(type=local, host="localhost")
        assert parse_host("127.0.0.1") == Host(type=tcp, host="127.0.0.1")
        assert parse_host("::1") == Host(type=tcp, host="::1")

        # HOST/LIMIT
        assert parse_host("localhost/64") == Host(type=local, host="localhost", limit="64")
        assert parse_host("127.0.0.1/64") == Host(type=tcp, host="127.0.0.1", limit="64")
        assert parse_host("::1/64") == Host(type=tcp, host="::1", limit="64")

        # HOST,COMPRESSION
        assert parse_host("localhost,lzo") == Host(type=local, host="localhost", compression="lzo")
        assert parse_host("127.0.0.1,lzo") == Host(type=tcp, host="127.0.0.1", compression="lzo")
        assert parse_host("::1,lzo") == Host(type=tcp, host="::1", compression="lzo")

        # HOST/LIMIT,COMPRESSION
        assert parse_host("localhost/64,lzo") == Host(type=local, host="localhost", limit="64", compression="lzo")
        assert parse_host("127.0.0.1/64,lzo") == Host(type=tcp, host="127.0.0.1", limit="64", compression="lzo")
        assert parse_host("::1/64,lzo") == Host(type=tcp, host="::1", limit="64", compression="lzo")

    def test_host_port(self):
        local: ConnectionType = ConnectionType.LOCAL
        tcp: ConnectionType = ConnectionType.TCP

        # HOST:PORT
        assert parse_host("localhost:3633") == Host(type=local, host="localhost", port="3633")
        assert parse_host("127.0.0.1:3633") == Host(type=tcp, host="127.0.0.1", port="3633")
        assert parse_host("[::1]:3633") == Host(type=tcp, host="::1", port="3633")

        # HOST:PORT/LIMIT
        assert parse_host("localhost:3633/64") == Host(type=local, host="localhost", limit="64", port="3633")
        assert parse_host("127.0.0.1:3633/64") == Host(type=tcp, host="127.0.0.1", limit="64", port="3633")
        assert parse_host("[::1]:3633/64") == Host(type=tcp, host="::1", limit="64", port="3633")

        # HOST:PORT,COMPRESSION
        assert parse_host("localhost:3633,lzo") == Host(type=local, host="localhost", compression="lzo", port="3633")
        assert parse_host("127.0.0.1:3633,lzo") == Host(type=tcp, host="127.0.0.1", compression="lzo", port="3633")
        assert parse_host("[::1]:3633,lzo") == Host(type=tcp, host="::1", compression="lzo", port="3633")

        # HOST:PORT/LIMIT,COMPRESSION
        assert parse_host("localhost:3633/64,lzo") == Host(
            type=local, host="localhost", limit="64", compression="lzo", port="3633"
        )
        assert parse_host("127.0.0.1:3633/64,lzo") == Host(
            type=tcp, host="127.0.0.1", limit="64", compression="lzo", port="3633"
        )
        assert parse_host("[::1]:3633/64,lzo") == Host(type=tcp, host="::1", limit="64", compression="lzo", port="3633")

    def test_at_host(self):
        local: ConnectionType = ConnectionType.LOCAL
        ssh: ConnectionType = ConnectionType.SSH

        # @HOST
        assert parse_host("@localhost") == Host(type=local, host="localhost")
        assert parse_host("@127.0.0.1") == Host(type=ssh, host="127.0.0.1")
        assert parse_host("@::1") == Host(type=ssh, host="::1")

        # @HOST/LIMIT
        assert parse_host("@localhost/64") == Host(type=local, host="localhost", limit="64")
        assert parse_host("@127.0.0.1/64") == Host(type=ssh, host="127.0.0.1", limit="64")
        assert parse_host("@::1/64") == Host(type=ssh, host="::1", limit="64")

        # @HOST,COMPRESSION
        assert parse_host("@localhost,lzo") == Host(type=local, host="localhost", compression="lzo")
        assert parse_host("@127.0.0.1,lzo") == Host(type=ssh, host="127.0.0.1", compression="lzo")
        assert parse_host("@::1,lzo") == Host(type=ssh, host="::1", compression="lzo")

        # @HOST/LIMIT,COMPRESSION
        assert parse_host("@localhost/64,lzo") == Host(type=local, host="localhost", limit="64", compression="lzo")
        assert parse_host("@127.0.0.1/64,lzo") == Host(type=ssh, host="127.0.0.1", limit="64", compression="lzo")
        assert parse_host("@::1/64,lzo") == Host(type=ssh, host="::1", limit="64", compression="lzo")

    def test_user_at_host(self):
        local: ConnectionType = ConnectionType.LOCAL
        ssh: ConnectionType = ConnectionType.SSH

        # USER@HOST
        assert parse_host("user@localhost") == Host(type=local, host="localhost", user="user")
        assert parse_host("user@127.0.0.1") == Host(type=ssh, host="127.0.0.1", user="user")
        assert parse_host("user@::1") == Host(type=ssh, host="::1", user="user")

        # USER@HOST/LIMIT
        assert parse_host("user@localhost/64") == Host(type=local, host="localhost", limit="64", user="user")
        assert parse_host("user@127.0.0.1/64") == Host(type=ssh, host="127.0.0.1", limit="64", user="user")
        assert parse_host("user@::1/64") == Host(type=ssh, host="::1", limit="64", user="user")

        # USER@HOST,COMPRESSION
        assert parse_host("user@localhost,lzo") == Host(type=local, host="localhost", compression="lzo", user="user")
        assert parse_host("user@127.0.0.1,lzo") == Host(type=ssh, host="127.0.0.1", compression="lzo", user="user")
        assert parse_host("user@::1,lzo") == Host(type=ssh, host="::1", compression="lzo", user="user")

        # USER@HOST/LIMIT,COMPRESSION
        assert parse_host("user@localhost/64,lzo") == Host(
            type=local, host="localhost", limit="64", compression="lzo", user="user"
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
        monkeypatch.delenv(HOMCC_HOSTS_ENV_VAR)

        # HOSTS file
        tmp_hosts_file: Path = tmp_path / HOMCC_HOSTS_FILENAME
        tmp_hosts_file.write_text("\n".join(hosts))

        assert load_hosts([tmp_hosts_file]) == hosts_no_whitespace


class TestParsingConfig:
    """
    Tests for client.parsing related to config files
    """

    config: List[str] = [
        "[homcc]",
        "# Client global config",
        "COMPILER=g++",
        "CoMpReSsIoN=lzo",
        "TIMEOUT=180",
        "profile=foobar",
        "log_level=INFO",
        "verbose=TRUE",
        # the following configs should be ignored
        "[homccd]",
        "LOG_LEVEL=DEBUG",
        "verbose=FALSE",
    ]

    config_overwrite: List[str] = [
        "[homcc]",
        "COMPILER=clang++",
        "verbose=FALSE",
    ]

    def test_parse_config_file(self, tmp_path: Path):
        tmp_config_file: Path = tmp_path / HOMCC_CONFIG_FILENAME
        tmp_config_file.write_text("\n".join(self.config))

        assert parse_config([tmp_config_file]) == ClientConfig(
            compiler="g++", compression="lzo", timeout=180, profile="foobar", log_level="INFO", verbose=True
        )

    def test_parse_multiple_config_files(self, tmp_path: Path):
        tmp_config_file: Path = tmp_path / HOMCC_CONFIG_FILENAME
        tmp_config_file.write_text("\n".join(self.config))

        tmp_config_file_overwrite: Path = tmp_path / f"{HOMCC_CONFIG_FILENAME}_overwrite"
        tmp_config_file_overwrite.write_text("\n".join(self.config_overwrite))

        assert parse_config([tmp_config_file_overwrite, tmp_config_file]) == ClientConfig(
            compiler="clang++", compression="lzo", timeout=180, profile="foobar", log_level="INFO", verbose=False
        )
