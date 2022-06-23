"""End to end integration tests, testing both the client and the server."""
import pytest

import os
import subprocess
import time

from pathlib import Path
from typing import List, Optional

from homcc.common.compression import Compression, NoCompression, LZO, LZMA


class TestEndToEnd:
    """End to end integration tests."""

    TEST_TIMEOUT: int = 10  # timeout value [s] for terminating tests

    BUF_SIZE: int = 65_536  # increased DEFAULT_BUFFER_SIZE to delay subprocess hangs

    ADDRESS: str = "127.0.0.1"  # avoid "localhost" in order to ensure remote compilation
    OUTPUT: str = "e2e_test"

    @staticmethod
    def homcc_args(unused_tcp_port: int, compression: Optional[Compression], profile: Optional[str]) -> List[str]:
        compression_arg = "" if compression is None or isinstance(compression, NoCompression) else f",{compression}"

        return [  # specify all relevant args explicitly so that config files may not disturb e2e testing
            "./homcc/client/main.py",
            "--log-level=DEBUG",
            "--verbose",
            f"--host={TestEndToEnd.ADDRESS}:{unused_tcp_port}/1{compression_arg}",
            "--no-profile" if profile is None else f"--profile={profile}",
            "--timeout=20",
        ]

    @staticmethod
    def start_server(unused_tcp_port: int) -> subprocess.Popen:
        return subprocess.Popen(
            [  # specify all relevant args explicitly so that config files may not disturb e2e testing
                "./homcc/server/main.py",
                f"--listen={TestEndToEnd.ADDRESS}",
                f"--port={unused_tcp_port}",
                "--jobs=1",
                "--verbose",
            ],
            bufsize=TestEndToEnd.BUF_SIZE,
            encoding="utf-8",
        )

    @staticmethod
    def start_client(
        args: List[str], unused_tcp_port: int, compression: Compression, profile: Optional[str]
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            TestEndToEnd.homcc_args(unused_tcp_port, compression, profile) + args,
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

    def cpp_end_to_end(
        self,
        compiler: str,
        unused_tcp_port: int,
        compression: Compression = NoCompression(),
        profile: Optional[str] = None,
    ):
        args: List[str] = [
            compiler,
            "-Iexample/include",
            "example/src/foo.cpp",
            "example/src/main.cpp",
            f"-o{self.OUTPUT}",
        ]

        with self.start_server(unused_tcp_port) as server_process:
            result = self.start_client(args, unused_tcp_port, compression, profile)

            self.check_remote_compilation_assertions(result)
            executable_stdout: str = subprocess.check_output([f"./{self.OUTPUT}"], encoding="utf-8")

            assert executable_stdout == "homcc\n"

            server_process.kill()

    def cpp_end_to_end_no_linking(
        self,
        compiler: str,
        unused_tcp_port: int,
        compression: Compression = NoCompression(),
        profile: Optional[str] = None,
    ):
        args: List[str] = [
            compiler,
            "-c",
            "-Iexample/include",
            "example/src/foo.cpp",
            "example/src/main.cpp",
            f"-o{TestEndToEnd.OUTPUT}",
        ]

        with self.start_server(unused_tcp_port) as server_process:
            result = self.start_client(args, unused_tcp_port, compression, profile)

            self.check_remote_compilation_assertions(result)

            assert os.path.exists(self.OUTPUT)

            server_process.kill()

    def cpp_end_to_end_preprocessor_side_effects(
        self,
        compiler: str,
        unused_tcp_port: int,
        compression: Compression = NoCompression(),
        profile: Optional[str] = None,
    ):
        args: List[str] = [
            compiler,
            "-Iexample/include",
            "-MD",
            "-MT",
            "main.cpp.o",
            "-MF",
            "main.cpp.o.d",
            "-o",
            "main.cpp.o",
            "-c",
            "example/src/main.cpp",
        ]

        with self.start_server(unused_tcp_port) as server_process:
            result = self.start_client(args, unused_tcp_port, compression, profile)

            self.check_remote_compilation_assertions(result)

            assert os.path.exists("main.cpp.o")
            assert os.path.exists("main.cpp.o.d")

            server_process.kill()

    def cpp_end_to_end_linking_only(
        self,
        compiler: str,
        unused_tcp_port: int,
        compression: Compression = NoCompression(),
        profile: Optional[str] = None,
    ):
        main_args: List[str] = [compiler, "-Iexample/include", "example/src/main.cpp", "-c"]
        foo_args: List[str] = [compiler, "-Iexample/include", "example/src/foo.cpp", "-c"]
        linking_args: List[str] = [compiler, "main.o", "foo.o", f"-o{self.OUTPUT}"]

        with self.start_server(unused_tcp_port) as server_process:
            main_result = self.start_client(main_args, unused_tcp_port, compression, profile)
            self.check_remote_compilation_assertions(main_result)
            assert os.path.exists("main.o")

            foo_result = self.start_client(foo_args, unused_tcp_port, compression, profile)
            self.check_remote_compilation_assertions(foo_result)
            assert os.path.exists("foo.o")

            linking_result = self.start_client(linking_args, unused_tcp_port, compression, profile)
            assert linking_result.returncode == os.EX_OK
            assert f"Linking [main.o, foo.o] to {self.OUTPUT}" in linking_result.stdout
            assert os.path.exists(self.OUTPUT)

            server_process.kill()

    def cpp_end_to_end_multiple_clients_shared_host(self, compiler: str, unused_tcp_port: int):
        # specify all relevant homcc args explicitly so that config files may not disturb e2e testing
        homcc_args: List[str] = self.homcc_args(unused_tcp_port, compression=None, profile=None)

        # specify different compilation args
        main_args: List[str] = [compiler, "-Iexample/include", "example/src/main.cpp", "-c"]
        foo_args: List[str] = [compiler, "-Iexample/include", "example/src/foo.cpp", "-c"]

        stdout_main: str = ""
        stdout_foo: str = ""

        with self.start_server(unused_tcp_port) as server_process, subprocess.Popen(
            homcc_args + main_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        ) as client_process_main, subprocess.Popen(
            homcc_args + foo_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        ) as client_process_foo:
            while client_process_main.poll() is None and client_process_foo.poll() is None:
                stdout_main += client_process_main.communicate()[0]
                stdout_foo += client_process_foo.communicate()[0]

            server_process.kill()

        assert client_process_main.returncode == os.EX_OK
        assert client_process_foo.returncode == os.EX_OK

        assert os.path.exists("main.o")
        assert os.path.exists("foo.o")

        # verify only one successful remote compilation by checking the processes stdouts
        assert ('"return_code": 0' in stdout_main and '"return_code": 0' not in stdout_foo) or (
            '"return_code": 0' not in stdout_main and '"return_code": 0' in stdout_foo
        )
        assert ("Compiling locally instead" not in stdout_main and "Compiling locally instead" in stdout_foo) or (
            "Compiling locally instead" in stdout_main and "Compiling locally instead" not in stdout_foo
        )

    @pytest.fixture(autouse=True)
    def clean_up(self):
        yield
        Path("main.o").unlink(missing_ok=True)
        Path("main.cpp.o").unlink(missing_ok=True)
        Path("main.cpp.o.d").unlink(missing_ok=True)
        Path("foo.o").unlink(missing_ok=True)
        Path(self.OUTPUT).unlink(missing_ok=True)

    # g++ tests
    @pytest.mark.gplusplus
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_end_to_end_gplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end("g++", unused_tcp_port)

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_end_to_end_lzo_gplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end("g++", unused_tcp_port, compression=LZO())

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_end_to_end_lzma_gplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end("g++", unused_tcp_port, compression=LZMA())

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_end_to_end_gplusplus_no_linking(self, unused_tcp_port: int):
        self.cpp_end_to_end_no_linking("g++", unused_tcp_port)

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_cpp_end_to_end_gplusplus_preprocessor_side_effects(self, unused_tcp_port: int):
        self.cpp_end_to_end_preprocessor_side_effects("g++", unused_tcp_port)

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_end_to_end_gplusplus_linking_only(self, unused_tcp_port: int):
        self.cpp_end_to_end_linking_only("g++", unused_tcp_port)

    @pytest.mark.gplusplus
    @pytest.mark.schroot
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_end_to_end_schroot_gplusplus(self, unused_tcp_port: int, schroot_profile: str):
        self.cpp_end_to_end("g++", unused_tcp_port, profile=schroot_profile)

    @pytest.mark.gplusplus
    @pytest.mark.schroot
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_end_to_end_schroot_gplusplus_no_linking(self, unused_tcp_port: int, schroot_profile: str):
        self.cpp_end_to_end_no_linking("g++", unused_tcp_port, profile=schroot_profile)

    @pytest.mark.gplusplus
    @pytest.mark.schroot
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_end_to_end_schroot_gplusplus_linking_only(self, unused_tcp_port: int, schroot_profile: str):
        self.cpp_end_to_end_linking_only("g++", unused_tcp_port, profile=schroot_profile)

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_end_to_end_gplusplus_shared_host_slot(self, unused_tcp_port: int):
        self.cpp_end_to_end_multiple_clients_shared_host("g++", unused_tcp_port)

    # clang++ tests
    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_end_to_end_clangplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end("clang++", unused_tcp_port)

    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_end_to_end_clangplusplus_no_linking(self, unused_tcp_port: int):
        self.cpp_end_to_end_no_linking("clang++", unused_tcp_port)

    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_cpp_end_to_end_clangplusplus_preprocessor_side_effects(self, unused_tcp_port: int):
        self.cpp_end_to_end_preprocessor_side_effects("clang++", unused_tcp_port)

    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_end_to_end_clangplusplus_linking_only(self, unused_tcp_port: int):
        self.cpp_end_to_end_linking_only("clang++", unused_tcp_port)

    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TEST_TIMEOUT)
    def test_end_to_end_clangplusplus_shared_host_slot(self, unused_tcp_port: int):
        self.cpp_end_to_end_multiple_clients_shared_host("clang++", unused_tcp_port)
