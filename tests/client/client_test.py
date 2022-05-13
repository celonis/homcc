""" Tests for client/client.py"""

import pytest
import struct

from typing import Iterator, List

from homcc.client.client import ClientState, HostSelector
from homcc.client.errors import HostsExhaustedError
from homcc.client.parsing import ConnectionType, Host, parse_host
from homcc.common.arguments import Arguments


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


class TestClientState:
    """Tests for ClientState"""

    def test_constants(self):
        # sanity checks to keep interoperability with distcc monitoring

        # size_t; unsigned long; unsigned long; char[128]; char[128]; int; enum (int); struct* (void*)
        assert ClientState.DISTCC_TASK_STATE_STRUCT_SIZE == 8 + 8 + 8 + 128 + 128 + 4 + 4 + 8 == 296
        assert ClientState.DISTCC_STATE_MAGIC == int.from_bytes(b"DIH\0", byteorder="big")

        for i, phases in enumerate(ClientState.DistccClientPhases):
            assert i == phases.value

    def test_bytes(self):
        args: List[str] = ["g++", "foo.cpp"]
        host: Host = Host(type=ConnectionType.TCP, host="remotehost")
        state: ClientState = ClientState(Arguments.from_args(args), host)
        state.pid = 13
        state.slot = 42

        # packing
        packed_state: bytes = bytes(state)
        assert packed_state == b"".join(
            [  # call individual struct packs here because it would be too tedious to test otherwise
                struct.pack("N", ClientState.DISTCC_TASK_STATE_STRUCT_SIZE),
                struct.pack("L", ClientState.DISTCC_STATE_MAGIC),
                struct.pack("L", state.pid),
                struct.pack("128s", state.source_base_filename.encode()),
                struct.pack("128s", state.hostname.encode()),
                struct.pack("i", state.slot),
                struct.pack("i", state.phase),
                struct.pack("P", 0),
            ]
        )

        # unpacking
        assert state == ClientState.from_bytes(packed_state)
