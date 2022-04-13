""" Tests for client/client.py"""

from pathlib import Path
from typing import Dict, List, Set

import pytest

from homcc.common.arguments import Arguments
from homcc.client.client import TCPClient
from homcc.client.compilation import calculate_dependency_dict, find_dependencies
from homcc.server.server import start_server, stop_server


class TestClient:
    """Tests for client/client.py"""

    @pytest.fixture(autouse=True)
    def _init(self, unused_tcp_port: int):
        server, server_thread = start_server(port=unused_tcp_port)

        self.client: TCPClient = TCPClient({"type": "TCP", "host": "localhost", "port": str(unused_tcp_port)})

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
