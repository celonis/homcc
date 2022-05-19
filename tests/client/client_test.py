""" Tests for client/client.py"""

import pytest

import fcntl
import struct

from pathlib import Path
from typing import Iterator, List

from homcc.client.client import HostSelector, HostSlotsLockFile, LockFile, Slots, StateFile
from homcc.client.errors import HostsExhaustedError, SlotsExhaustedError
from homcc.client.parsing import Host, parse_host, ConnectionType


class TestHostSelector:
    """Tests for HostSelector"""

    # first host will be ignored by the host selector due to 0 limit
    HOSTS: List[str] = ["remotehost0/0", "remotehost1/1", "remotehost2/2", "remotehost3/4", "remotehost4/8"]
    PARSED_HOSTS: List[Host] = [parse_host(host) for host in HOSTS]

    def test_host_selector(self):
        host_selector: HostSelector = HostSelector(self.HOSTS)

        host_iter: Iterator = iter(host_selector)
        for count, host in enumerate(host_iter):
            assert host in self.PARSED_HOSTS
            assert count == len(self.HOSTS[1:]) - len(host_selector) - 1

        assert len(host_selector) == 0
        with pytest.raises(StopIteration):
            assert next(host_iter)

    def test_host_selector_with_tries(self):
        host_selector: HostSelector = HostSelector(self.HOSTS, 3)

        host_iter: Iterator = iter(host_selector)
        for _ in range(3):
            host: Host = next(host_iter)
            assert host in self.PARSED_HOSTS

        assert len(host_selector) == 1
        with pytest.raises(HostsExhaustedError):
            assert next(host_iter)

    def test_host_selector_with_tries_not_enough_hosts(self):
        host_selector: HostSelector = HostSelector([self.HOSTS[1]], 3)

        assert len(host_selector) == 1

        host_iter: Iterator = iter(host_selector)
        host: Host = next(host_iter)
        assert host == self.PARSED_HOSTS[1]

        assert len(host_selector) == 0
        with pytest.raises(StopIteration):
            assert next(host_iter)


class TestSlots:
    """Tests for Slots"""

    def test_slots(self):
        for size in [1, 4, 12, 48, 96]:  # some arbitrary values
            slots: Slots = Slots(b"\x00" * size)

            assert slots == b"\x00" * size
            assert slots == Slots.with_size(size)
            assert slots.none_locked()
            assert not slots.all_locked()

            assert slots.get_unlocked_slot() is not None

            for i in range(size):
                assert not slots.is_locked(i)
                slots.lock_slot(i)
                assert not slots.none_locked()

            assert slots == b"\xFF" * size
            assert slots.all_locked()
            assert slots.get_unlocked_slot() is None

            assert slots.unlock_slot(0)
            assert not slots.is_locked(0)
            assert slots == b"\x00" + b"\xFF" * (size - 1)
            assert slots.get_unlocked_slot() == 0


class TestLockFile:
    """Tests for LockFile"""

    def test_lockfile(self, tmp_path: Path):
        filepath: Path = tmp_path / "test"
        filepath.touch()

        with LockFile(filepath):  # first access
            with pytest.raises(IOError):
                with open(filepath, mode="rb") as file:
                    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_UN)  # second access (not blocking)


class TestHostSlotsLockFile:
    """Tests for HostSlotsLockFile"""

    def test_host_slots_lockfile(self, tmp_path: Path):
        host: Host = Host(type=ConnectionType.LOCAL, name="localhost", limit="1")
        filepath: Path = tmp_path / str(host)  # will be created by HostSlotsLockFile
        assert not filepath.exists()

        with HostSlotsLockFile(host, tmp_path):  # locking first and only lock
            assert filepath.exists()
            assert filepath.read_bytes() == b"\xFF"

            with pytest.raises(SlotsExhaustedError):
                with HostSlotsLockFile(host, tmp_path):  # trying to lock the same slot
                    pass

        assert not filepath.exists()


class TestStateFile:
    """Tests for StateFile"""

    def test_constants(self):
        """sanity checks to keep interoperability with distcc monitoring"""

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
