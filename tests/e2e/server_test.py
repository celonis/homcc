"""End to end integration tests, testing both the client and the server."""

import subprocess
import pytest

from pathlib import Path


class TestEndToEnd:
    """End to end integration tests."""

    def start_server(self) -> subprocess.Popen:
        return subprocess.Popen(["./homcc_server.py"], stdout=subprocess.PIPE)

    def start_client(self) -> str:
        return subprocess.check_output(
            [
                "./homcc_client.py",
                "g++",
                "-Iexample/include",
                "example/src/foo.cpp",
                "example/src/main.cpp",
                "-oe2e-test",
            ],
            stderr=subprocess.STDOUT,
        ).decode("utf-8")

    @pytest.fixture(autouse=True)
    def clean_up(self):
        yield
        Path("e2e-test").unlink(missing_ok=True)

    @pytest.mark.timeout(60)
    def test_end_to_end(self):
        with self.start_server():
            client_stdout = self.start_client()

            # make sure we actually compiled at the server (and did not fall back to local compilation),
            # i.e. look at the log messages if the compilation of the file on the server side was okay
            assert '"return_code": 0' in client_stdout

            binary_stdout = subprocess.check_output(["./e2e-test"]).decode("utf-8")
            assert binary_stdout == "homcc\n"
