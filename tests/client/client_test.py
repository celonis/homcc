""" Tests for client/client.py"""
import threading
import time

import pytest

import posix_ipc
import struct

from pathlib import Path
from typing import Iterator, List

from homcc.client.client import HostSelector, LocalHostSemaphore, RemoteHostSemaphore, StateFile
from homcc.client.errors import HostsExhaustedError, SlotsExhaustedError
from homcc.client.parsing import ConnectionType, Host


class TestHostSelector:
    """Tests for HostSelector"""

    # first host will be ignored by the host selector due to 0 limit
    HOSTS: List[Host] = [
        Host.from_str(host_str)
        for host_str in ["remotehost0/0", "remotehost1/1", "remotehost2/2", "remotehost3/4", "remotehost4/8"]
    ]

    def test_host_selector(self):
        host_selector: HostSelector = HostSelector(self.HOSTS)

        assert len(host_selector) == 4

        host_iter: Iterator = iter(host_selector)
        for count, host in enumerate(host_iter):
            assert host in self.HOSTS
            assert count == len(self.HOSTS[1:]) - len(host_selector) - 1

        assert len(host_selector) == 0
        with pytest.raises(StopIteration):
            assert next(host_iter)

    def test_host_selector_with_tries(self):
        host_selector: HostSelector = HostSelector(self.HOSTS, 3)

        assert len(host_selector) == 4

        host_iter: Iterator = iter(host_selector)
        for _ in range(3):
            host: Host = next(host_iter)
            assert host in self.HOSTS

        assert len(host_selector) == 1
        with pytest.raises(HostsExhaustedError):
            assert next(host_iter)

    def test_host_selector_with_tries_not_enough_hosts(self):
        host_selector: HostSelector = HostSelector(self.HOSTS[1:2], 3)

        assert len(host_selector) == 1

        host_iter: Iterator = iter(host_selector)
        host: Host = next(host_iter)
        assert host == self.HOSTS[1]

        assert len(host_selector) == 0
        with pytest.raises(StopIteration):
            assert next(host_iter)


class TestRemoteHostSemaphore:
    """Tests for RemoteHostSemaphore"""

    def test_localhost(self):
        localhost: Host = Host(type=ConnectionType.LOCAL, name="localhost")

        with pytest.raises(ValueError):
            with RemoteHostSemaphore(localhost):
                pass

    def test_remotehosts(self, unused_tcp_port: int):
        name: str = self.test_remotehosts.__name__
        remotehost: Host = Host(type=ConnectionType.TCP, name=name, port=unused_tcp_port, limit=1)
        host_id: str = remotehost.id()

        with RemoteHostSemaphore(remotehost):  # successful first acquire
            assert Path(f"/dev/shm/sem.{host_id}")
            assert posix_ipc.Semaphore(host_id).value == 0

            with pytest.raises(SlotsExhaustedError):
                with RemoteHostSemaphore(remotehost):  # failing second acquire
                    pass

        assert posix_ipc.Semaphore(host_id).value == 1  # successful release


class TestLocalHostSemaphore:
    """Tests for LocalHostSemaphore"""

    def test_remotehost(self):
        remotehost: Host = Host(type=ConnectionType.TCP, name="remotehost")

        with pytest.raises(ValueError):
            with LocalHostSemaphore(remotehost):
                pass

    @pytest.mark.timeout(5)
    def test_localhosts(self):
        localhost: Host = Host(type=ConnectionType.LOCAL, name="localhost", limit=1)
        localhost.name = self.test_localhosts.__name__
        host_id: str = localhost.id()

        def hold_semaphore(host: Host):
            with LocalHostSemaphore(host, 2):  # successful acquire
                assert Path(f"/dev/shm/sem.{host_id}")
                assert posix_ipc.Semaphore(host_id).value == 0
                time.sleep(1)

        # single hold
        hold_semaphore(localhost)
        assert posix_ipc.Semaphore(host_id).value == 1  # successful release

        # concurrent holds
        threads: List[threading.Thread] = [
            threading.Thread(target=task, args=(localhost,)) for task in 2 * [hold_semaphore]
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        assert posix_ipc.Semaphore(host_id).value == 1  # successful releases


class TestStateFile:
    """Tests for StateFile"""

    def test_constants(self):
        """sanity checks to keep interoperability with distcc monitoring tools"""

        # size_t(8); unsigned long(8); unsigned long(8); char[128]; char[128]; int(4); enum{=int}(4); struct*{=void*}(8)
        assert StateFile.DISTCC_TASK_STATE_STRUCT_SIZE == 8 + 8 + 8 + 128 + 128 + 4 + 4 + 8
        assert StateFile.DISTCC_STATE_MAGIC == int.from_bytes(b"DIH\0", byteorder="big")  # confirm comment

        for i, phases in enumerate(StateFile.DISTCC_CLIENT_PHASES):
            assert i == phases.value

    def test_bytes(self):
        state_file: StateFile = StateFile("foo.cpp", "hostname", 42)
        state_file.phase = StateFile.DISTCC_CLIENT_PHASES.STARTUP

        packed_state: bytes = bytes(state_file)
        assert packed_state == b"".join(
            [  # individual struct packing because it would be too tedious to test byte equality otherwise
                struct.pack("N", StateFile.DISTCC_TASK_STATE_STRUCT_SIZE),
                struct.pack("L", StateFile.DISTCC_STATE_MAGIC),
                struct.pack("L", state_file.pid),
                struct.pack("128s", state_file.source_base_filename),
                struct.pack("128s", state_file.hostname),
                struct.pack("i", state_file.slot),
                struct.pack("i", state_file.phase),
                struct.pack("P", StateFile.DISTCC_NEXT_TASK_STATE),
            ]
        )

        assert state_file == StateFile.from_bytes(packed_state)

    def test_set_phase(self, tmp_path: Path):
        with StateFile("foo.cpp", "hostname", 42, state_dir=tmp_path) as state_file:
            assert state_file.filepath.exists()  # file touched

            for phase in StateFile.DISTCC_CLIENT_PHASES:
                state_file.set_phase(phase)  # phase set and status written to file
                assert state_file.phase == phase
                assert StateFile.from_bytes(state_file.filepath.read_bytes()).phase == phase
