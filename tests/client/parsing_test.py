# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

""" Tests for client/parsing.py"""
import os
import subprocess
from pathlib import Path
from typing import List

import pytest
from pytest import CaptureFixture
from pytest_mock.plugin import MockerFixture

from homcc import client
from homcc.client.config import parse_config
from homcc.client.parsing import (
    HOMCC_HOSTS_ENV_VAR,
    HOMCC_HOSTS_FILENAME,
    ClientConfig,
    Host,
    load_hosts,
    parse_cli_args,
)
from homcc.common.constants import ENCODING
from homcc.common.errors import HostParsingError
from homcc.common.host import ConnectionType
from homcc.common.parsing import HOMCC_CONFIG_FILENAME


class TestCLI:
    """Tests for client.parsing.parse_cli_args"""

    MOCKED_HOSTS: List[str] = ["localhost/8", "remotehost/64"]

    @pytest.fixture(autouse=True)
    def setup_mock(self, mocker: MockerFixture):
        mocker.patch(
            "homcc.client.parsing.load_hosts",
            return_value=("", self.MOCKED_HOSTS),
        )

    def test_version(self, capfd: CaptureFixture):
        with pytest.raises(SystemExit) as sys_exit:
            parse_cli_args(["./homcc/client/main.py", "--version"])

        cap = capfd.readouterr()

        assert sys_exit.value.code == os.EX_OK
        assert not cap.err
        assert f"homcc {client.__version__}" in cap.out

    def test_show_hosts(self, capfd: CaptureFixture):
        with pytest.raises(SystemExit) as sys_exit:
            parse_cli_args(["./homcc/client/main.py", "--show-hosts"])

        cap = capfd.readouterr()

        assert sys_exit.value.code == os.EX_OK
        assert not cap.err
        assert len(cap.out.splitlines()) == len(self.MOCKED_HOSTS)
        for host in self.MOCKED_HOSTS:
            assert host in cap.out

    def test_show_concurrency_level(self, capfd: CaptureFixture):
        with pytest.raises(SystemExit) as sys_exit:
            parse_cli_args(["./homcc/client/main.py", "-j"])

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
            encoding=ENCODING,
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
            "remotehost:3126/-1",
            "@remotehost/-1",
            "user@remotehost/-1",
        ]

        for failing_host in failing_hosts:
            with pytest.raises(HostParsingError):
                _ = Host.from_str(failing_host)

    def test_parse_host_trailing_comment(self):
        # NAME#COMMENT
        assert Host.from_str("localhost#COMMENT") == Host(type=ConnectionType.LOCAL, name="localhost")
        assert Host.from_str("localhost/64#COMMENT") == Host(type=ConnectionType.LOCAL, name="localhost", limit=64)
        assert Host.from_str("localhost,lzo#COMMENT") == Host(
            type=ConnectionType.LOCAL, name="localhost", compression="lzo"
        )
        assert Host.from_str("localhost/64,lzo#COMMENT") == Host(
            type=ConnectionType.LOCAL, name="localhost", limit=64, compression="lzo"
        )

    def test_host(self):
        local: ConnectionType = ConnectionType.LOCAL
        tcp: ConnectionType = ConnectionType.TCP

        # NAME
        assert Host.from_str("localhost") == Host(type=local, name="localhost")
        assert Host.from_str("127.0.0.1") == Host(type=tcp, name="127.0.0.1")
        assert Host.from_str("::1") == Host(type=tcp, name="::1")

        # NAME/LIMIT
        assert Host.from_str("localhost/64") == Host(type=local, name="localhost", limit=64)
        assert Host.from_str("127.0.0.1/64") == Host(type=tcp, name="127.0.0.1", limit=64)
        assert Host.from_str("::1/64") == Host(type=tcp, name="::1", limit=64)

        # NAME,COMPRESSION
        assert Host.from_str("localhost,lzo") == Host(type=local, name="localhost", compression="lzo")
        assert Host.from_str("127.0.0.1,lzo") == Host(type=tcp, name="127.0.0.1", compression="lzo")
        assert Host.from_str("::1,lzo") == Host(type=tcp, name="::1", compression="lzo")

        # NAME/LIMIT,COMPRESSION
        assert Host.from_str("localhost/64,lzo") == Host(type=local, name="localhost", limit=64, compression="lzo")
        assert Host.from_str("127.0.0.1/64,lzo") == Host(type=tcp, name="127.0.0.1", limit=64, compression="lzo")
        assert Host.from_str("::1/64,lzo") == Host(type=tcp, name="::1", limit=64, compression="lzo")

    def test_host_port(self):
        local: ConnectionType = ConnectionType.LOCAL
        tcp: ConnectionType = ConnectionType.TCP

        # NAME:PORT
        assert Host.from_str("localhost:3126") == Host(type=local, name="localhost", port=3126)
        assert Host.from_str("127.0.0.1:3126") == Host(type=tcp, name="127.0.0.1", port=3126)
        assert Host.from_str("[::1]:3126") == Host(type=tcp, name="::1", port=3126)

        # NAME:PORT/LIMIT
        assert Host.from_str("localhost:3126/64") == Host(type=local, name="localhost", limit=64, port=3126)
        assert Host.from_str("127.0.0.1:3126/64") == Host(type=tcp, name="127.0.0.1", limit=64, port=3126)
        assert Host.from_str("[::1]:3126/64") == Host(type=tcp, name="::1", limit=64, port=3126)

        # NAME:PORT,COMPRESSION
        assert Host.from_str("localhost:3126,lzo") == Host(type=local, name="localhost", compression="lzo", port=3126)
        assert Host.from_str("127.0.0.1:3126,lzo") == Host(type=tcp, name="127.0.0.1", compression="lzo", port=3126)
        assert Host.from_str("[::1]:3126,lzo") == Host(type=tcp, name="::1", compression="lzo", port=3126)

        # NAME:PORT/LIMIT,COMPRESSION
        assert Host.from_str("localhost:3126/64,lzo") == Host(
            type=local, name="localhost", limit=64, compression="lzo", port=3126
        )
        assert Host.from_str("127.0.0.1:3126/64,lzo") == Host(
            type=tcp, name="127.0.0.1", limit=64, compression="lzo", port=3126
        )
        assert Host.from_str("[::1]:3126/64,lzo") == Host(type=tcp, name="::1", limit=64, compression="lzo", port=3126)

    def test_at_host(self):
        local: ConnectionType = ConnectionType.LOCAL
        ssh: ConnectionType = ConnectionType.SSH

        # @NAME
        assert Host.from_str("@localhost") == Host(type=local, name="localhost")
        assert Host.from_str("@127.0.0.1") == Host(type=ssh, name="127.0.0.1")
        assert Host.from_str("@::1") == Host(type=ssh, name="::1")

        # @NAME/LIMIT
        assert Host.from_str("@localhost/64") == Host(type=local, name="localhost", limit=64)
        assert Host.from_str("@127.0.0.1/64") == Host(type=ssh, name="127.0.0.1", limit=64)
        assert Host.from_str("@::1/64") == Host(type=ssh, name="::1", limit=64)

        # @NAME,COMPRESSION
        assert Host.from_str("@localhost,lzo") == Host(type=local, name="localhost", compression="lzo")
        assert Host.from_str("@127.0.0.1,lzo") == Host(type=ssh, name="127.0.0.1", compression="lzo")
        assert Host.from_str("@::1,lzo") == Host(type=ssh, name="::1", compression="lzo")

        # @NAME/LIMIT,COMPRESSION
        assert Host.from_str("@localhost/64,lzo") == Host(type=local, name="localhost", limit=64, compression="lzo")
        assert Host.from_str("@127.0.0.1/64,lzo") == Host(type=ssh, name="127.0.0.1", limit=64, compression="lzo")
        assert Host.from_str("@::1/64,lzo") == Host(type=ssh, name="::1", limit=64, compression="lzo")

    def test_user_at_host(self):
        local: ConnectionType = ConnectionType.LOCAL
        ssh: ConnectionType = ConnectionType.SSH

        # USER@NAME
        assert Host.from_str("user@localhost") == Host(type=local, name="localhost", user="user")
        assert Host.from_str("user@127.0.0.1") == Host(type=ssh, name="127.0.0.1", user="user")
        assert Host.from_str("user@::1") == Host(type=ssh, name="::1", user="user")

        # USER@NAME/LIMIT
        assert Host.from_str("user@localhost/64") == Host(type=local, name="localhost", limit=64, user="user")
        assert Host.from_str("user@127.0.0.1/64") == Host(type=ssh, name="127.0.0.1", limit=64, user="user")
        assert Host.from_str("user@::1/64") == Host(type=ssh, name="::1", limit=64, user="user")

        # USER@NAME,COMPRESSION
        assert Host.from_str("user@localhost,lzo") == Host(type=local, name="localhost", compression="lzo", user="user")
        assert Host.from_str("user@127.0.0.1,lzo") == Host(type=ssh, name="127.0.0.1", compression="lzo", user="user")
        assert Host.from_str("user@::1,lzo") == Host(type=ssh, name="::1", compression="lzo", user="user")

        # USER@NAME/LIMIT,COMPRESSION
        assert Host.from_str("user@localhost/64,lzo") == Host(
            type=local, name="localhost", limit=64, compression="lzo", user="user"
        )
        assert Host.from_str("user@127.0.0.1/64,lzo") == Host(
            type=ssh, name="127.0.0.1", limit=64, compression="lzo", user="user"
        )
        assert Host.from_str("user@::1/64,lzo") == Host(type=ssh, name="::1", limit=64, compression="lzo", user="user")

    def test_load_hosts(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        hosts = ["localhost", "localhost:3126 ", "localhost:3126,lzo\t", " ", ""]
        hosts_no_whitespace = ["localhost", "localhost:3126", "localhost:3126,lzo"]

        # $HOMCC_HOSTS
        monkeypatch.setenv(HOMCC_HOSTS_ENV_VAR, "\n".join(hosts))
        assert load_hosts() == (HOMCC_HOSTS_ENV_VAR, hosts_no_whitespace)
        monkeypatch.delenv(HOMCC_HOSTS_ENV_VAR)

        # HOSTS file
        tmp_hosts_file: Path = tmp_path / HOMCC_HOSTS_FILENAME
        tmp_hosts_file.write_text("\n".join(hosts))

        assert load_hosts([tmp_hosts_file]) == (str(tmp_hosts_file), hosts_no_whitespace)


class TestParsingConfig:
    """
    Tests for client.parsing related to config files
    """

    config: List[str] = [
        "[homcc]",
        "# Client global config",
        "CoMpReSsIoN=lzo",
        "COMPILATION_REQUEST_TIMEOUT=180",
        "schroot_profile=foobar",
        "docker_container=some_container",
        "log_level=INFO",
        "verbose=TRUE",
        # the following configs should be ignored
        "[homccd]",
        "LOG_LEVEL=DEBUG",
        "verbose=FALSE",
    ]

    config_overwrite: List[str] = [
        "[homcc]",
        "verbose=FALSE",
    ]

    def test_parse_config_file(self, tmp_path: Path):
        tmp_config_file: Path = tmp_path / HOMCC_CONFIG_FILENAME
        tmp_config_file.write_text("\n".join(self.config))

        assert parse_config([tmp_config_file]) == ClientConfig(
            files=[str(tmp_config_file.absolute())],
            compression="lzo",
            compilation_request_timeout=180,
            log_level="INFO",
            verbose=True,
            schroot_profile="foobar",
            docker_container="some_container",
        )

    def test_parse_multiple_config_files(self, tmp_path: Path):
        tmp_config_file: Path = tmp_path / HOMCC_CONFIG_FILENAME
        tmp_config_file.write_text("\n".join(self.config))

        tmp_config_file_overwrite: Path = tmp_path / f"{HOMCC_CONFIG_FILENAME}_overwrite"
        tmp_config_file_overwrite.write_text("\n".join(self.config_overwrite))

        assert parse_config([tmp_config_file_overwrite, tmp_config_file]) == ClientConfig(
            files=[str(file.absolute()) for file in [tmp_config_file, tmp_config_file_overwrite]],
            compression="lzo",
            compilation_request_timeout=180,
            schroot_profile="foobar",
            docker_container="some_container",
            log_level="INFO",
            verbose=False,
        )


class TestHost:
    """Tests the Host class."""

    def test_id(self):
        assert Host.from_str("8.8.8.8:3126/64").id() != Host.from_str("8.8.8.8:3127/64").id()
        assert Host.from_str("other_hostname:3126/64").id() != Host.from_str("some_hostname:3126/64").id()

        assert Host.from_str("8.8.8.8:3127/64").id() == Host.from_str("8.8.8.8:3127/64").id()
        assert Host.from_str("some_hostname:3126/64").id() == Host.from_str("some_hostname:3126/64").id()
