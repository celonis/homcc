import pytest

from homcc.client.client import *
from homcc.client.client_utils import *
from homcc.server.server import start_server, stop_server
from pathlib import Path


class TestClient:
    # pylint: disable=W0201
    @pytest.fixture(autouse=True)
    def _init(self, unused_tcp_port: int):
        host: str = "localhost"
        server, server_thread = start_server(port=unused_tcp_port)

        self.client: TCPClient = TCPClient(host, unused_tcp_port)

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
    @pytest.mark.timeout(1)
    async def test_connectivity_and_send_argument_message(self):
        args: List[str] = ["g++", str(self.example_main_cpp.absolute()),
                           str(self.example_foo_cpp.absolute()),
                           f"-I{str(self.example_inc_dir.absolute())}",
                           "-o", str(self.example_out_file.absolute())]
        cwd: str = ""
        dependency_list: List[str] = find_dependencies(args)
        assert not dependency_list  # TODO(s.pirsch): remove
        dependency_hashes: Dict[str, str] = calculate_dependency_hashes(cwd, dependency_list)
        timeout_send: int = 1

        await self.client.connect()
        await self.client.send_argument_message(args, cwd, dependency_hashes, timeout_send)
        await self.client.close()
