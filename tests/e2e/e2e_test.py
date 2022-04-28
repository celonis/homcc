"""End to end integration tests, testing both the client and the server."""
import pytest

import os
import shutil
import subprocess

from pathlib import Path


class TestEndToEnd:
    """End to end integration tests."""

    output: str = "e2e_test"

    @staticmethod
    def start_server(unused_tcp_port: int) -> subprocess.Popen:
        return subprocess.Popen(["./homcc/server/main.py", f"--port={unused_tcp_port}"], stdout=subprocess.PIPE)

    @staticmethod
    def start_client(compiler: str, unused_tcp_port: int) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "./homcc/client/main.py",
                compiler,
                f"--host=127.0.0.1:{unused_tcp_port}",  # avoid "localhost" here in order to ensure remote compilation
                "--verbose",
                "-Iexample/include",
                "example/src/foo.cpp",
                "example/src/main.cpp",
                f"-o{TestEndToEnd.output}",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

    @staticmethod
    def cpp_end_to_end(compiler: str, unused_tcp_port: int):
        with TestEndToEnd.start_server(unused_tcp_port) as server_process:
            result = TestEndToEnd.start_client(compiler, unused_tcp_port)

            # make sure we actually compile at the server (and did not fall back to local compilation),
            # i.e. look at the log messages if the compilation of the file on the server side was okay
            assert result.returncode == os.EX_OK
            assert '"return_code": 0' in result.stdout
            assert "Compiling locally instead" not in result.stdout

            executable_stdout = subprocess.check_output([f"./{TestEndToEnd.output}"], encoding="utf-8")
            assert executable_stdout == "homcc\n"

            server_process.kill()

    @pytest.fixture(autouse=True)
    def clean_up(self):
        yield
        Path(TestEndToEnd.output).unlink(missing_ok=True)

    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    @pytest.mark.timeout(10)
    def test_end_to_end_gplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end("g++", unused_tcp_port)

    @pytest.mark.skipif(shutil.which("clang++") is None, reason="clang++ is not installed")
    @pytest.mark.timeout(10)
    def test_end_to_end_clangplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end("clang++", unused_tcp_port)
