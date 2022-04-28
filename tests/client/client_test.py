""" Tests for client/client.py"""

from pathlib import Path
from typing import Dict, Iterator, List, Set

import pytest

from homcc.common.arguments import Arguments
from homcc.client.client import HostSelector, HostsExhaustedError, TCPClient
from homcc.client.compilation import calculate_dependency_dict, find_dependencies
from homcc.client.parsing import ConnectionType, Host, parse_host
from homcc.common.compression import NoCompression
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


class TestTCPClient:
    """Tests for TCPClient"""

    @pytest.fixture(autouse=True)
    def _init(self, unused_tcp_port: int):
        server, server_thread = start_server(address="localhost", port=unused_tcp_port, limit=1)

        self.client: TCPClient = TCPClient(
            Host(type=ConnectionType.TCP, host="localhost", port=str(unused_tcp_port)), NoCompression()
        )

        self.example_base_dir: Path = Path("example")
        self.example_main_cpp: Path = self.example_base_dir / "src" / "main.cpp"
        self.example_foo_cpp: Path = self.example_base_dir / "src" / "foo.cpp"
        self.example_inc_dir: Path = self.example_base_dir / "include"
        self.example_out_dir: Path = self.example_base_dir / "build"
        self.example_out_file: Path = self.example_out_dir / "foo"

        yield  # individual tests run here

        stop_server(server)
        server_thread.join()

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_connectivity_and_send_argument_message(self):
        args: List[str] = [
            "g++",
            str(self.example_main_cpp.absolute()),
            str(self.example_foo_cpp.absolute()),
            f"-I{str(self.example_inc_dir.absolute())}",
            "-o",
            str(self.example_out_file.absolute()),
        ]
        cwd: str = ""
        dependencies: Set[str] = find_dependencies(Arguments.from_args(args))
        dependency_dict: Dict[str, str] = calculate_dependency_dict(dependencies)

        await self.client.connect()
        await self.client.send_argument_message(Arguments.from_args(args), cwd, dependency_dict)
        await self.client.close()
