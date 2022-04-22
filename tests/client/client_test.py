""" Tests for client/client.py"""

from pathlib import Path
from typing import Dict, Iterator, List, Set

import pytest

from homcc.common.arguments import Arguments
from homcc.client.client import LoadBalancer, TCPClient
from homcc.client.compilation import calculate_dependency_dict, find_dependencies
from homcc.client.parsing import ConnectionType, Host, parse_host
from homcc.server.server import start_server, stop_server


class TestLoadBalancer:
    """Tests for LoadBalancer"""

    def test_load_balancer(self):
        hosts: List[str] = ["remotehost1/1", "remotehost2/2", "remotehost3/4", "remotehost4/8"]
        parsed_hosts: List[Host] = [parse_host(host) for host in hosts]
        tickets: int = 1 + 2 + 4 + 8
        count: int = -1

        load_balancer: LoadBalancer = LoadBalancer(hosts)

        host_iter: Iterator = iter(load_balancer)
        for count, host in enumerate(host_iter):
            assert host in parsed_hosts
            tickets -= host.limit

        assert tickets == 0
        assert count == len(hosts) - 1
        with pytest.raises(StopIteration):
            assert next(host_iter)


class TestTCPClient:
    """Tests for TCPClient"""

    @pytest.fixture(autouse=True)
    def _init(self, unused_tcp_port: int):
        server, server_thread = start_server(port=unused_tcp_port)

        self.client: TCPClient = TCPClient(Host(type=ConnectionType.TCP, host="localhost", port=str(unused_tcp_port)))

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
