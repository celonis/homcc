"""End to end integration tests, testing both the client and the server."""
import pytest

import os
import shutil
import subprocess
import time

from pathlib import Path
from typing import List

from homcc.common.compression import Compression, NoCompression, LZO, LZMA


class TestEndToEnd:
    """End to end integration tests."""

    ADDRESS: str = "127.0.0.1"  # avoid "localhost" in order to ensure remote compilation
    OUTPUT: str = "e2e_test"

    @staticmethod
    def start_server(unused_tcp_port: int) -> subprocess.Popen:
        return subprocess.Popen(
            ["./homcc/server/main.py", f"--listen={TestEndToEnd.ADDRESS}", f"--port={unused_tcp_port}"]
        )

    @staticmethod
    def start_client(args: List[str], unused_tcp_port: int, compression: Compression) -> subprocess.CompletedProcess:
        compression_arg = "" if isinstance(compression, NoCompression) else f",{str(compression)}"
        return subprocess.run(
            [
                "./homcc/client/main.py",
                f"--host={TestEndToEnd.ADDRESS}:{unused_tcp_port}{compression_arg}",
                "--verbose",
            ]
            + args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

    @pytest.fixture(autouse=True)
    def delay_between_tests(self):
        yield
        time.sleep(2)

    @staticmethod
    def check_remote_compilation_assertions(result: subprocess.CompletedProcess):
        # make sure we actually compile at the server (and did not fall back to local compilation),
        # i.e. look at the log messages if the compilation of the file on the server side was okay
        assert result.returncode == os.EX_OK
        assert '"return_code": 0' in result.stdout
        assert "Compiling locally instead" not in result.stdout

    def cpp_end_to_end(self, compiler: str, unused_tcp_port: int, compression: Compression = NoCompression()):
        args: List[str] = [
            compiler,
            "-Iexample/include",
            "example/src/foo.cpp",
            "example/src/main.cpp",
            f"-o{TestEndToEnd.OUTPUT}",
        ]
        with self.start_server(unused_tcp_port) as server_process:
            result = self.start_client(args, unused_tcp_port, compression)
            self.check_remote_compilation_assertions(result)
            executable_stdout: str = subprocess.check_output([f"./{self.OUTPUT}"], encoding="utf-8")

            assert executable_stdout == "homcc\n"

            server_process.kill()

    def cpp_end_to_end_no_linking(
        self, compiler: str, unused_tcp_port: int, compression: Compression = NoCompression()
    ):
        args: List[str] = [
            compiler,
            "-Iexample/include",
            "example/src/foo.cpp",
            "example/src/main.cpp",
            f"-o{TestEndToEnd.OUTPUT}",
            "-c",
        ]

        with self.start_server(unused_tcp_port) as server_process:
            result = self.start_client(args, unused_tcp_port, compression)

            self.check_remote_compilation_assertions(result)

            assert os.path.exists(self.OUTPUT)

            server_process.kill()

    def cpp_end_to_end_linking_only(
        self, compiler: str, unused_tcp_port: int, compression: Compression = NoCompression()
    ):
        main_args: List[str] = [compiler, "-Iexample/include", "example/src/main.cpp", "-c"]
        foo_args: List[str] = [compiler, "-Iexample/include", "example/src/foo.cpp", "-c"]
        linking_args: List[str] = [compiler, "main.o", "foo.o", f"-o{TestEndToEnd.OUTPUT}"]

        with self.start_server(unused_tcp_port) as server_process:
            main_result = self.start_client(main_args, unused_tcp_port, compression)
            self.check_remote_compilation_assertions(main_result)
            assert os.path.exists("main.o")

            foo_result = self.start_client(foo_args, unused_tcp_port, compression)
            self.check_remote_compilation_assertions(foo_result)
            assert os.path.exists("foo.o")

            linking_result = self.start_client(linking_args, unused_tcp_port, compression)
            assert linking_result.returncode == os.EX_OK
            assert f"Linking [main.o, foo.o] to {self.OUTPUT}" in linking_result.stdout
            assert os.path.exists(self.OUTPUT)

            server_process.kill()

    @pytest.fixture(autouse=True)
    def clean_up(self):
        yield
        Path("main.o").unlink(missing_ok=True)
        Path("foo.o").unlink(missing_ok=True)
        Path(self.OUTPUT).unlink(missing_ok=True)

    @pytest.mark.timeout(20)
    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    def test_end_to_end_gplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end("g++", unused_tcp_port)

    @pytest.mark.timeout(20)
    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    def test_end_to_end_gplusplus_lzo(self, unused_tcp_port: int):
        self.cpp_end_to_end("g++", unused_tcp_port, compression=LZO())

    @pytest.mark.timeout(20)
    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    def test_end_to_end_gplusplus_lzma(self, unused_tcp_port: int):
        self.cpp_end_to_end("g++", unused_tcp_port, compression=LZMA())

    @pytest.mark.timeout(20)
    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    def test_end_to_end_gplusplus_no_linking(self, unused_tcp_port: int):
        self.cpp_end_to_end_no_linking("g++", unused_tcp_port)

    @pytest.mark.timeout(20)
    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    def test_end_to_end_gplusplus_linking_only(self, unused_tcp_port: int):
        self.cpp_end_to_end_linking_only("g++", unused_tcp_port)

    @pytest.mark.timeout(20)
    @pytest.mark.skipif(shutil.which("clang++") is None, reason="clang++ is not installed")
    def test_end_to_end_clangplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end("clang++", unused_tcp_port)

    @pytest.mark.timeout(20)
    @pytest.mark.skipif(shutil.which("clang++") is None, reason="clang++ is not installed")
    def test_end_to_end_clangplusplus_no_linking(self, unused_tcp_port: int):
        self.cpp_end_to_end_no_linking("clang++", unused_tcp_port)

    @pytest.mark.timeout(20)
    @pytest.mark.skipif(shutil.which("clang++") is None, reason="clang++ is not installed")
    def test_end_to_end_clangplusplus_linking_only(self, unused_tcp_port: int):
        self.cpp_end_to_end_linking_only("clang++", unused_tcp_port)
