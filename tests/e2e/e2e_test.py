"""End to end integration tests, testing both the client and the server."""
import os
import subprocess
import pytest

from pathlib import Path


class TestEndToEnd:
    """End to end integration tests."""

    def start_server(self) -> subprocess.Popen:
        return subprocess.Popen(["./homcc/server/main.py"], stdout=subprocess.PIPE)

    def start_client(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "./homcc/client/main.py",
                "g++",
                "-Iexample/include",
                "example/src/foo.cpp",
                "example/src/main.cpp",
                "-oe2e-test",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            # TODO(s.pirsch): add --DEBUG flag when external client configuration is implemented (CPL-6419)
        )

    @pytest.fixture(autouse=True)
    def clean_up(self):
        yield
        Path("e2e-test").unlink(missing_ok=True)

    @pytest.mark.timeout(10)
    def test_end_to_end(self):

        with self.start_server() as server_process:
            result = self.start_client()

            # make sure we actually compiled at the server (and did not fall back to local compilation),
            # i.e. look at the log messages if the compilation of the file on the server side was okay
            assert result.returncode == os.EX_OK
            assert "Compiling locally instead" not in result.stdout

            binary_stdout = subprocess.check_output(["./e2e-test"]).decode("utf-8")
            assert binary_stdout == "homcc\n"

            server_process.kill()
