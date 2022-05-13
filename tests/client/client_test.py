""" Tests for client/client.py"""

import pytest
import struct

from pathlib import Path
from typing import Iterator, List

from homcc.client.client import ClientStateFile, HostSelector
from homcc.client.errors import HostsExhaustedError
from homcc.client.parsing import Host, parse_host


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


class TestClientStateFile:
    """Tests for ClientState"""

    def test_constants(self):
        """sanity checks to keep interoperability with distcc monitoring"""

        # size_t; unsigned long; unsigned long; char[128]; char[128]; int; enum (int); struct* (void*)
        assert ClientStateFile.DISTCC_TASK_STATE_STRUCT_SIZE == 8 + 8 + 8 + 128 + 128 + 4 + 4 + 8 == 296
        assert ClientStateFile.DISTCC_STATE_MAGIC == int.from_bytes(b"DIH\0", byteorder="big")  # confirm comment

        for i, phases in enumerate(ClientStateFile.DistccClientPhases):
            assert i == phases.value

    def test_bytes(self):
        state_file: ClientStateFile = ClientStateFile("foo.cpp", "hostname", 42)
        state_file.phase = ClientStateFile.DistccClientPhases.STARTUP

        # packing
        packed_state: bytes = bytes(state_file)
        assert packed_state == b"".join(
            [  # call individual struct packing because it would be too tedious to test otherwise
                struct.pack("N", ClientStateFile.DISTCC_TASK_STATE_STRUCT_SIZE),
                struct.pack("L", ClientStateFile.DISTCC_STATE_MAGIC),
                struct.pack("L", state_file.pid),
                struct.pack("128s", state_file.source_base_filename),
                struct.pack("128s", state_file.hostname),
                struct.pack("i", state_file.slot),
                struct.pack("i", state_file.phase),
                struct.pack("P", ClientStateFile.DISTCC_NEXT_TASK_STATE),
            ]
        )

        # unpacking
        assert state_file == ClientStateFile.from_bytes(packed_state)

    def test_startup(self, tmp_path: Path):
        with ClientStateFile("foo.cpp", "hostname", 42, state_dir=tmp_path) as state_file:
            # state_file.file = Path()
            state_file.startup()
            assert state_file.phase == ClientStateFile.DistccClientPhases.STARTUP
