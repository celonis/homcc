"""End to end integration tests, testing both the client and the server."""
import pytest

import os
import subprocess

from pathlib import Path


class TestEndToEnd:
    """End to end integration tests."""

    @staticmethod
    def start_server(unused_tcp_port: int) -> subprocess.Popen:
        return subprocess.Popen(["./homcc/server/main.py", f"--port={unused_tcp_port}"], stdout=subprocess.PIPE)

    @staticmethod
    def start_client(unused_tcp_port: int) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "./homcc/client/main.py",
                "g++",
                f"--host=localhost:{unused_tcp_port}",
                "--verbose",
                "-Iexample/include",
                "example/src/foo.cpp",
                "example/src/main.cpp",
                "-oe2e-test",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

    @pytest.fixture(autouse=True)
    def clean_up(self):
        yield
        Path("e2e-test").unlink(missing_ok=True)

    @pytest.mark.timeout(10)
    def test_end_to_end(self, unused_tcp_port: int):
        with self.start_server(unused_tcp_port) as server_process:
            result = self.start_client(unused_tcp_port)

            # make sure we actually compile at the server (and did not fall back to local compilation),
            # i.e. look at the log messages if the compilation of the file on the server side was okay
            assert result.returncode == os.EX_OK
            assert '"return_code": 0' in result.stdout
            assert "Compiling locally instead" not in result.stdout

            executable_stdout = subprocess.check_output(["./e2e-test"], encoding="utf-8")
            assert executable_stdout == "homcc\n"

            server_process.kill()
