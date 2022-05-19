"""End to end integration tests, testing both the client and the server."""
import pytest

import os
import shutil
import subprocess
import time

from pathlib import Path
from typing import List, Optional

from homcc.common.compression import Compression, NoCompression, LZO, LZMA


class TestEndToEnd:
    """End to end integration tests."""

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
            ]
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
            f"-o{TestEndToEnd.OUTPUT}",
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

    def cpp_end_to_end_linking_only(
        self,
        compiler: str,
        unused_tcp_port: int,
        compression: Compression = NoCompression(),
        profile: Optional[str] = None,
    ):
        main_args: List[str] = [compiler, "-Iexample/include", "example/src/main.cpp", "-c"]
        foo_args: List[str] = [compiler, "-Iexample/include", "example/src/foo.cpp", "-c"]
        linking_args: List[str] = [compiler, "main.o", "foo.o", f"-o{TestEndToEnd.OUTPUT}"]

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
    def test_end_to_end_lzo_gplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end("g++", unused_tcp_port, compression=LZO())

    @pytest.mark.timeout(20)
    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    def test_end_to_end_lzma_gplusplus(self, unused_tcp_port: int):
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

    @pytest.mark.schroot
    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    @pytest.mark.timeout(20)
    def test_end_to_end_schroot_gplusplus(self, unused_tcp_port: int, schroot_profile: str):
        self.cpp_end_to_end("g++", unused_tcp_port, profile=schroot_profile)

    @pytest.mark.schroot
    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    @pytest.mark.timeout(20)
    def test_end_to_end_schroot_gplusplus_no_linking(self, unused_tcp_port: int, schroot_profile: str):
        self.cpp_end_to_end_no_linking("g++", unused_tcp_port, profile=schroot_profile)

    @pytest.mark.schroot
    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    @pytest.mark.timeout(20)
    def test_end_to_end_schroot_gplusplus_linking_only(self, unused_tcp_port: int, schroot_profile: str):
        self.cpp_end_to_end_linking_only("g++", unused_tcp_port, profile=schroot_profile)

    # @pytest.mark.xfail(reason="Two compilation requests require the same host slot")
    @pytest.mark.timeout(20)
    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    def test_end_to_end_gplusplus_shared_host_slot(self, unused_tcp_port: int):
        # specify all relevant homcc args explicitly so that config files may not disturb e2e testing
        homcc_args: List[str] = self.homcc_args(unused_tcp_port, None, None)

        # specify different compilation args
        main_args: List[str] = [
            "g++",
            "-c",
            "-Iexample/include",
            "example/src/main.cpp",
            "-omain.o",
        ]
        foo_args: List[str] = [
            "g++",
            "-c",
            "-Iexample/include",
            "example/src/foo.cpp",
            "-ofoo.o",
        ]

        process_args: List[List[str]] = [homcc_args + main_args, homcc_args + foo_args]

        with self.start_server(unused_tcp_port) as server_process:
            processes: List[subprocess.Popen] = [
                # pylint: disable=R1732
                subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8")
                for args in process_args
            ]

            for process in processes:
                assert process.wait() == os.EX_OK

            stdouts: List[str] = [process.communicate()[0] for process in processes]

            # check for successful remote compilation in only one of the processes
            assert ('"return_code": 0' in stdouts[0] and '"return_code": 0' not in stdouts[1]) or (
                '"return_code": 0' not in stdouts[0] and '"return_code": 0' in stdouts[1]
            )
            assert ("Compiling locally instead" not in stdouts[0] and "Compiling locally instead" in stdouts[1]) or (
                "Compiling locally instead" in stdouts[0] and "Compiling locally instead" not in stdouts[1]
            )

            assert os.path.exists("main.o")
            assert os.path.exists("foo.o")

            server_process.kill()
