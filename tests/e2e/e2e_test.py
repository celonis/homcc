"""End to end integration tests, testing both the client and the server."""

import subprocess
import pytest

from pathlib import Path


class TestEndToEnd:
    """End to end integration tests."""

    def start_server(self) -> subprocess.Popen:
        return subprocess.Popen(["./homcc/server/main.py"], stdout=subprocess.PIPE)

    def start_client(self) -> str:
        return subprocess.check_output(
            [
                "./homcc/client/main.py",
                "g++",
                "-Iexample/include",
                "example/src/foo.cpp",
                "example/src/main.cpp",
                "-oe2e-test",
            ],
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

    @pytest.fixture(autouse=True)
    def clean_up(self):
        yield
        Path("e2e-test").unlink(missing_ok=True)

    @pytest.mark.timeout(10)
    def test_end_to_end(self):

        with self.start_server() as server_process:
            client_stdout = self.start_client()

            # make sure we actually compiled at the server (and did not fall back to local compilation),
            # i.e. look at the log messages if the compilation of the file on the server side was okay
            assert '"return_code": 0' in client_stdout
            assert "Compiling locally instead" not in client_stdout

            binary_stdout = subprocess.check_output(["./e2e-test"]).decode("utf-8")
            assert binary_stdout == "homcc\n"

            server_process.kill()
