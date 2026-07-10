# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Tests for the SSH transport of the homcc client."""
import subprocess
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from homcc.client.client import TCPClient
from homcc.client.compilation import create_remote_client
from homcc.client.config import ClientConfig
from homcc.client.ssh import DEFAULT_SSH_CONTROL_PERSIST, SSHClient, SSHTunnel
from homcc.common.arguments import Arguments
from homcc.common.errors import SSHError
from homcc.common.host import ConnectionType, Host
from homcc.common.statefile import StateFile


class TestSSHTunnel:
    """Tests for the SSHTunnel connection multiplexing manager."""

    # deliberately inspect internals to verify the multiplexing/forwarding behavior
    # pylint: disable=protected-access

    def test_target(self):
        assert SSHTunnel(Host.from_str("user@buildhost")).target == "user@buildhost"
        assert SSHTunnel(Host.from_str("@buildhost")).target == "buildhost"

    def test_control_path_is_stable_and_unique(self, tmp_path: Path, mocker: MockerFixture):
        mocker.patch("homcc.client.ssh._ssh_base_dir", return_value=tmp_path)

        # identical hosts share the same control socket, so concurrent processes converge on one tunnel
        assert SSHTunnel(Host.from_str("user@buildhost")).control_path == (
            SSHTunnel(Host.from_str("user@buildhost")).control_path
        )
        # different user / host / remote port must not collide
        assert SSHTunnel(Host.from_str("user@buildhost")).control_path != (
            SSHTunnel(Host.from_str("other@buildhost")).control_path
        )
        assert SSHTunnel(Host.from_str("user@buildhost:3126")).control_path != (
            SSHTunnel(Host.from_str("user@buildhost:3127")).control_path
        )

    def test_control_args_enable_multiplexing(self):
        tunnel = SSHTunnel(
            Host.from_str("user@buildhost"), ssh_executable="/usr/bin/ssh", ssh_options=["-o", "BatchMode=yes"]
        )
        args = tunnel._control_args()

        assert args[0] == "/usr/bin/ssh"
        assert "ControlMaster=auto" in args
        assert f"ControlPath={tunnel.control_path}" in args
        assert args[-2:] == ["-o", "BatchMode=yes"]

    def test_ensure_reuses_alive_master(self, tmp_path: Path, mocker: MockerFixture):
        mocker.patch("homcc.client.ssh._ssh_base_dir", return_value=tmp_path)
        tunnel = SSHTunnel(Host.from_str("user@buildhost"))

        mocker.patch.object(tunnel, "_is_master_alive", return_value=True)
        tunnel._port_file.parent.mkdir(parents=True, exist_ok=True)
        tunnel._port_file.write_text("54321")
        start_master = mocker.patch.object(tunnel, "_start_master")

        assert tunnel.ensure(timeout=10) == 54321
        start_master.assert_not_called()  # no new SSH handshake when a master already exists

    def test_ensure_starts_master_when_absent(self, tmp_path: Path, mocker: MockerFixture):
        mocker.patch("homcc.client.ssh._ssh_base_dir", return_value=tmp_path)
        tunnel = SSHTunnel(Host.from_str("user@buildhost"))

        mocker.patch.object(tunnel, "_is_master_alive", return_value=False)
        mocker.patch("homcc.client.ssh._find_free_local_port", return_value=45678)
        run = mocker.patch("homcc.client.ssh.subprocess.run", return_value=subprocess.CompletedProcess([], 0))

        assert tunnel.ensure(timeout=10) == 45678
        assert tunnel._port_file.read_text() == "45678"

        command = run.call_args.args[0]
        assert "-M" in command and "-N" in command
        assert "45678:localhost:3126" in command  # local port forwarded to the daemon on the remote loopback
        assert command[-1] == "user@buildhost"

    def test_ensure_raises_ssh_error_on_failure(self, tmp_path: Path, mocker: MockerFixture):
        mocker.patch("homcc.client.ssh._ssh_base_dir", return_value=tmp_path)
        tunnel = SSHTunnel(Host.from_str("user@buildhost"))

        mocker.patch.object(tunnel, "_is_master_alive", return_value=False)
        mocker.patch("homcc.client.ssh._find_free_local_port", return_value=45678)
        mocker.patch(
            "homcc.client.ssh.subprocess.run",
            return_value=subprocess.CompletedProcess([], 255, stderr=b"Permission denied"),
        )

        with pytest.raises(SSHError, match="Permission denied"):
            tunnel.ensure(timeout=10)

    def test_ensure_raises_ssh_error_on_timeout(self, tmp_path: Path, mocker: MockerFixture):
        mocker.patch("homcc.client.ssh._ssh_base_dir", return_value=tmp_path)
        tunnel = SSHTunnel(Host.from_str("user@buildhost"))

        mocker.patch.object(tunnel, "_is_master_alive", return_value=False)
        mocker.patch("homcc.client.ssh._find_free_local_port", return_value=45678)
        mocker.patch("homcc.client.ssh.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=1))

        with pytest.raises(SSHError, match="timed out"):
            tunnel.ensure(timeout=1)


class TestClientFactory:
    """Tests that the remote client factory dispatches on the host connection type."""

    # deliberately inspect the tunnel wired into the SSH client
    # pylint: disable=protected-access

    @staticmethod
    def _state(host: Host, tmp_path: Path) -> StateFile:
        return StateFile(Arguments.from_vargs("gcc", "foo.cpp"), host, state_dir=tmp_path)

    def test_tcp_host_creates_tcp_client(self, tmp_path: Path):
        host = Host.from_str("buildhost:3126")
        client = create_remote_client(host, timeout=10, state=self._state(host, tmp_path), config=ClientConfig.empty())

        assert isinstance(client, TCPClient)
        assert client.connection_target == "buildhost:3126"

    def test_ssh_host_creates_ssh_client(self, tmp_path: Path):
        host = Host.from_str("user@buildhost")
        config = ClientConfig(files=[], ssh_control_persist=42, ssh_options=["-o", "BatchMode=yes"])
        client = create_remote_client(host, timeout=10, state=self._state(host, tmp_path), config=config)

        assert isinstance(client, SSHClient)
        assert host.type == ConnectionType.SSH
        assert client.connection_target == "user@buildhost"
        assert client._tunnel.control_persist == 42
        assert client._tunnel.ssh_options == ["-o", "BatchMode=yes"]

    def test_ssh_tunnel_default_control_persist(self, tmp_path: Path):
        host = Host.from_str("@buildhost")
        client = create_remote_client(host, timeout=10, state=self._state(host, tmp_path), config=ClientConfig.empty())

        assert isinstance(client, SSHClient)
        assert client._tunnel.control_persist == DEFAULT_SSH_CONTROL_PERSIST
