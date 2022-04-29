""" Tests for client/client.py"""

from typing import Dict, Iterator, List, Set

import pytest

from homcc.common.arguments import Arguments
from homcc.client.client import HostSelector, TCPClient
from homcc.client.compilation import calculate_dependency_dict, find_dependencies
from homcc.client.errors import HostsExhaustedError
from homcc.client.parsing import ConnectionType, Host, parse_host
from homcc.server.server import start_server, stop_server


class TestHostSelector:
    """Tests for HostSelector"""

    # first host will be ignored by the host selector due to 0 limit
    hosts: List[str] = ["remotehost0/0", "remotehost1/1", "remotehost2/2", "remotehost3/4", "remotehost4/8"]
    parsed_hosts: List[Host] = [parse_host(host) for host in hosts]

    def test_host_selector(self):
        host_selector: HostSelector = HostSelector(self.hosts)

        host_iter: Iterator = iter(host_selector)
        for count, host in enumerate(host_iter):
            assert host in self.parsed_hosts
            assert count == len(self.hosts[1:]) - len(host_selector) - 1

        assert len(host_selector) == 0
        with pytest.raises(StopIteration):
            assert next(host_iter)

    def test_host_selector_with_tries(self):
        host_selector: HostSelector = HostSelector(self.hosts, 3)

        host_iter: Iterator = iter(host_selector)
        for _ in range(3):
            host: Host = next(host_iter)
            assert host in self.parsed_hosts

        assert len(host_selector) == 1
        with pytest.raises(HostsExhaustedError):
            assert next(host_iter)

    def test_host_selector_with_tries_not_enough_hosts(self):
        host_selector: HostSelector = HostSelector([self.hosts[1]], 3)

        assert len(host_selector) == 1

        host_iter: Iterator = iter(host_selector)
        host: Host = next(host_iter)
        assert host == self.parsed_hosts[1]

        assert len(host_selector) == 0
        with pytest.raises(StopIteration):
            assert next(host_iter)


class TestTCPClient:
    """Tests for TCPClient"""

    output: str = "tcp_client_test"

    @pytest.fixture(autouse=True)
    def _init(self, unused_tcp_port: int):
        server, server_thread = start_server(address="localhost", port=unused_tcp_port, limit=1)

        self.client: TCPClient = TCPClient(Host(type=ConnectionType.TCP, host="127.0.0.1", port=str(unused_tcp_port)))

        yield  # individual tests run here

        stop_server(server)
        server_thread.join()

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_connectivity_and_send_argument_message(self):
        args: List[str] = [
            "g++",
            "-Iexample/include",
            "example/src/foo.cpp",
            "example/src/main.cpp",
            f"-o{TestTCPClient.output}",
        ]
        cwd: str = "/home/user/homcc_tcp_client_test"
        dependencies: Set[str] = find_dependencies(Arguments.from_args(args))
        dependency_dict: Dict[str, str] = calculate_dependency_dict(dependencies)

        async with self.client as client:
            await client.send_argument_message(Arguments.from_args(args), cwd, dependency_dict)
