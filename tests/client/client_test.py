""" Tests for client/client.py"""

import os
import threading
import time
from pathlib import Path
from typing import Iterator, List

import pytest
import sysv_ipc

from homcc.client.client import (
    HostSelector,
    LocalHostSemaphore,
    RemoteHostSemaphore,
    StateFile,
)
from homcc.client.parsing import ConnectionType, Host
from homcc.common.errors import HostsExhaustedError, SlotsExhaustedError


class TestHostSelector:
    """Tests for HostSelector"""

    # first host will be ignored by the host selector due to 0 limit
    HOSTS: List[Host] = [
        Host.from_str(host_str)
        # the first two hosts will be skipped per default
        for host_str in [
            "localhost/1",
            "remotehost0/0",
            "remotehost1/1",
            "remotehost2/2",
            "remotehost3/4",
            "remotehost4/8",
        ]
    ]

    def test_localhost_selector(self):
        host_selector: HostSelector = HostSelector(self.HOSTS[0:1], tries=1, allow_localhost=True)

        assert len(host_selector) == 1

        host: Host = next(iter(host_selector))
        assert host == self.HOSTS[0]
        assert host.is_local()

    def test_host_selector(self):
        host_selector: HostSelector = HostSelector(self.HOSTS)

        assert len(host_selector) == 4

        host_iter: Iterator = iter(host_selector)
        for count, host in enumerate(host_iter):
            assert host in self.HOSTS
            assert count == len(self.HOSTS[2:]) - len(host_selector) - 1

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
        host_selector: HostSelector = HostSelector(self.HOSTS[2:3], 3)

        assert len(host_selector) == 1

        host_iter: Iterator = iter(host_selector)
        host: Host = next(host_iter)
        assert host == self.HOSTS[2]

        assert len(host_selector) == 0
        with pytest.raises(StopIteration):
            assert next(host_iter)


class TestRemoteHostSemaphore:
    """Tests for RemoteHostSemaphore"""

    def test_localhost(self):
        localhost: Host = Host.localhost_with_limit(1)

        with pytest.raises(ValueError):
            with RemoteHostSemaphore(localhost):
                pass

    def test_remotehosts(self, unused_tcp_port: int):
        name: str = self.test_remotehosts.__name__  # dedicated test semaphore
        remotehost: Host = Host(type=ConnectionType.TCP, name=name, port=unused_tcp_port, limit=1)
        host_id: int = remotehost.id()

        with RemoteHostSemaphore(remotehost):  # successful first acquire
            assert Path(f"/dev/shm/sem.{host_id}")
            assert sysv_ipc.Semaphore(host_id).value == 0

            with pytest.raises(SlotsExhaustedError):
                with RemoteHostSemaphore(remotehost):  # failing second acquire
                    pass

        with pytest.raises(sysv_ipc.ExistentialError):
            # check if semaphore got cleaned up
            sysv_ipc.Semaphore(host_id)

    def test_release(self, unused_tcp_port: int):
        name: str = self.test_release.__name__  # dedicated test semaphore
        remotehost: Host = Host(type=ConnectionType.TCP, name=name, port=unused_tcp_port, limit=1)
        host_id: int = remotehost.id()

        with pytest.raises(SystemExit):
            with RemoteHostSemaphore(remotehost):
                assert Path(f"/dev/shm/sem.{host_id}")
                assert sysv_ipc.Semaphore(host_id).value == 0
                raise SystemExit(os.EX_TEMPFAIL)

        with pytest.raises(sysv_ipc.ExistentialError):
            # check if semaphore got cleaned up
            sysv_ipc.Semaphore(host_id)


class TestLocalHostSemaphore:
    """Tests for LocalHostSemaphore"""

    def test_remotehost(self):
        remotehost: Host = Host(type=ConnectionType.TCP, name="remotehost")

        with pytest.raises(ValueError):
            with LocalHostSemaphore(remotehost):
                pass

    # ignore signal handling in non-main threads warning
    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    @pytest.mark.timeout(5)
    def test_localhosts(self):
        localhost: Host = Host.localhost_with_limit(1)
        localhost.name = self.test_localhosts.__name__  # overwrite name to create dedicated test semaphore
        host_id: int = localhost.id()

        def hold_semaphore(host: Host):
            with LocalHostSemaphore(host, 2):  # successful acquire
                assert sysv_ipc.Semaphore(host_id).value == 0
                time.sleep(1)

        # single hold: 1sec total
        hold_semaphore(localhost)
        with pytest.raises(sysv_ipc.ExistentialError):
            # check if semaphore got cleaned up
            sysv_ipc.Semaphore(host_id)

        # concurrent holds: 2 or 3sec total
        threads: List[threading.Thread] = [
            threading.Thread(target=task, args=(localhost,)) for task in 2 * [hold_semaphore]
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        with pytest.raises(sysv_ipc.ExistentialError):
            # check if semaphore got cleaned up
            sysv_ipc.Semaphore(host_id)

    def test_release(self):
        localhost: Host = Host.localhost_with_limit(1)
        localhost.name = self.test_localhosts.__name__  # overwrite name to create dedicated test semaphore
        host_id: int = localhost.id()

        with pytest.raises(SystemExit):
            with LocalHostSemaphore(localhost, 2):
                assert Path(f"/dev/shm/sem.{host_id}")
                assert sysv_ipc.Semaphore(host_id).value == 0
                raise SystemExit(os.EX_TEMPFAIL)

        with pytest.raises(sysv_ipc.ExistentialError):
            # check if semaphore got cleaned up
            sysv_ipc.Semaphore(host_id)


class TestStateFile:
    """Tests for StateFile"""

    def test_constants(self):
        """sanity checks to keep interoperability with distcc monitoring tools"""

        # size_t(8); unsigned long(8); unsigned long(8); char[128]; char[128]; int(4); enum{=int}(4); struct*{=void*}(8)
        assert StateFile.DISTCC_TASK_STATE_STRUCT_SIZE == 8 + 8 + 8 + 128 + 128 + 4 + 4 + 8
        assert StateFile.DISTCC_STATE_MAGIC == int.from_bytes(b"DIH\0", byteorder="big")  # confirm comment

        for i, phases in enumerate(StateFile.ClientPhase):
            assert i == phases.value
