# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""
SSH transport for the homcc client.

Remote compilation over SSH is implemented as a tunnel to an already running `homccd`: an OpenSSH master connection is
established once per remote host and local-forwards a port to the daemon's loopback port on the remote. Subsequent
compilations reuse that master via OpenSSH connection multiplexing (ControlMaster/ControlPersist), so the per-job cost
is reduced to a local TCP connection to the forwarded port instead of a full SSH handshake. Because every tunneled
connection reaches the same daemon as direct TCP clients, the server keeps enforcing its global connection/compilation
limit across both transports.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import logging
import os
import socket
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from homcc.client.client import RemoteCompilationClient
from homcc.common.constants import ENCODING, TCP_BUFFER_SIZE
from homcc.common.errors import SSHError
from homcc.common.host import Host
from homcc.common.parsing import (
    HOMCC_CONFIG_FILENAME,
    HOMCC_DIR_ENV_VAR,
    default_locations,
)
from homcc.common.statefile import StateFile

logger = logging.getLogger(__name__)

DEFAULT_SSH_EXECUTABLE: str = "ssh"
DEFAULT_SSH_CONTROL_PERSIST: int = 600
"""Seconds an idle multiplexed SSH master connection is kept alive for reuse."""


def _ssh_base_dir() -> Path:
    """Directory holding the SSH control sockets and forwarded-port state files."""
    homcc_dir_env_var: Optional[str] = os.getenv(HOMCC_DIR_ENV_VAR)
    if homcc_dir_env_var:
        return Path(homcc_dir_env_var) / "ssh"

    for config_location in default_locations(HOMCC_CONFIG_FILENAME):
        return config_location.parent / "ssh"

    return Path.home() / ".homcc" / "ssh"


def _find_free_local_port() -> int:
    """Ask the OS for a currently free local TCP port to forward through the SSH tunnel."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class SSHTunnel:
    """
    Manages a multiplexed OpenSSH master connection with a local port-forward to a remote `homccd`.

    A single master connection is shared across all concurrent homcc processes that target the same remote host via
    the ssh control socket. Setting up the master is guarded by a per-host file lock so that the many homcc
    invocations a build system spawns converge on one tunnel instead of racing to create their own.
    """

    def __init__(
        self,
        host: Host,
        *,
        ssh_executable: str = DEFAULT_SSH_EXECUTABLE,
        control_persist: int = DEFAULT_SSH_CONTROL_PERSIST,
        ssh_options: Optional[List[str]] = None,
    ):
        self.host = host
        self.remote_port: int = host.port
        self.ssh_executable = ssh_executable
        self.control_persist = control_persist
        self.ssh_options: List[str] = ssh_options or []

        # unique but filesystem-path-length safe identifier for the (user, host, remote port) triple
        user: str = host.user or ""
        key: str = f"{user}@{host.name}:{host.port}"
        digest: str = hashlib.sha1(key.encode(ENCODING)).hexdigest()[:16]

        base_dir: Path = _ssh_base_dir()
        self.control_path: Path = base_dir / f"{digest}.sock"
        self._port_file: Path = base_dir / f"{digest}.port"
        self._lock_file: Path = base_dir / f"{digest}.lock"

    @property
    def target(self) -> str:
        """SSH target argument, i.e. 'user@host' or 'host'."""
        return f"{self.host.user}@{self.host.name}" if self.host.user else self.host.name

    @property
    def control_args(self) -> List[str]:
        """Common OpenSSH arguments enabling connection multiplexing via the shared control socket."""
        return [
            self.ssh_executable,
            "-o",
            "ControlMaster=auto",
            "-o",
            f"ControlPath={self.control_path}",
            *self.ssh_options,
        ]

    def _is_master_alive(self) -> bool:
        """Return whether a reusable multiplexed master connection already exists for this host."""
        check = subprocess.run(  # noqa: PLW1510
            [*self.control_args, "-O", "check", self.target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return check.returncode == 0

    def _start_master(self, timeout: float) -> int:
        """Start the multiplexed master with a local port-forward and return the chosen local port."""
        local_port: int = _find_free_local_port()

        # -M/-S: act as multiplexing master over the control socket
        # -f -N: background after authentication without executing a remote command
        # -L: forward local_port to the daemon on the remote loopback interface
        # ExitOnForwardFailure: fail fast if the forward can not be set up rather than silently continuing
        command: List[str] = [
            *self.control_args,
            "-M",
            "-S",
            str(self.control_path),
            "-o",
            f"ControlPersist={self.control_persist}",
            "-o",
            "ExitOnForwardFailure=yes",
            "-f",
            "-N",
            "-L",
            f"{local_port}:localhost:{self.remote_port}",
            self.target,
        ]

        logger.debug("Establishing SSH master connection to '%s' (local port %i).", self.target, local_port)
        try:
            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=True,
            )
        except subprocess.TimeoutExpired as error:
            raise SSHError(f"Establishing the SSH tunnel to '{self.target}' timed out.") from error
        except subprocess.CalledProcessError as error:
            stderr: str = error.stderr.decode(ENCODING, errors="replace").strip()
            raise SSHError(f"Could not establish the SSH tunnel to '{self.target}': {stderr}") from error
        except OSError as error:
            raise SSHError(f"Could not execute '{self.ssh_executable}': {error}") from error

        self._port_file.write_text(str(local_port), encoding=ENCODING)
        return local_port

    def ensure(self, timeout: float) -> int:
        """
        Ensure a live multiplexed tunnel exists and return the forwarded local port.

        Reuses an existing master connection when possible; otherwise sets one up while holding a per-host file lock so
        that concurrent homcc processes do not each spawn their own tunnel.
        """
        self.control_path.parent.mkdir(parents=True, exist_ok=True)

        if self._is_master_alive() and self._port_file.exists():
            return int(self._port_file.read_text(encoding=ENCODING))

        with self._lock_file.open("w", encoding=ENCODING) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                # re-check under the lock: another process may have set up the master while we waited
                if self._is_master_alive() and self._port_file.exists():
                    return int(self._port_file.read_text(encoding=ENCODING))
                return self._start_master(timeout)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


class SSHClient(RemoteCompilationClient):
    """Client to exchange homcc protocol messages with a remote server through an SSH tunnel to a running `homccd`."""

    def __init__(self, host: Host, timeout: float, state: StateFile, tunnel: SSHTunnel):
        super().__init__(host, timeout, state)

        self._tunnel = tunnel
        self.connection_target = tunnel.target

    async def _open_connection(self) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        # establishing/reusing the SSH master may block on subprocess calls, so run it off the event loop; the overall
        # setup and connect is still bounded by the connection timeout applied by the base class
        local_port: int = await asyncio.to_thread(self._tunnel.ensure, self.timeout)
        return await asyncio.open_connection(host="127.0.0.1", port=local_port, limit=TCP_BUFFER_SIZE)
