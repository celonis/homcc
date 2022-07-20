"""End to end integration tests, testing both the client and the server."""
from __future__ import annotations
import pytest

import os
import subprocess
import time

from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

from homcc.common.compression import Compression, NoCompression, LZO, LZMA


class TestEndToEnd:
    """
    End-to-end integration tests.

    Some of the following tests are flaky as they rely on the OS dispatcher and are therefore inherently unpredictable
    due to scheduling. We try to mitigate these issues by introducing waiting periods for certain tasks.

    As many tests are very repetitive this class provides additional helper classes and functions.
    """

    TIMEOUT: int = 10  # timeout value [s] for terminating e2e tests

    BUF_SIZE: int = 65_536  # increased DEFAULT_BUFFER_SIZE to delay subprocess hangs

    ADDRESS: str = "127.0.0.1"  # avoid "localhost" in order to ensure remote compilation
    OUTPUT: str = "e2e_test"

    @dataclass
    class BasicClientArguments:
        """Wrapper holding basic arguments supplied to the client for E2E testing."""

        compiler: str
        tcp_port: int
        compression: Optional[Compression] = NoCompression()
        schroot_profile: Optional[str] = None
        docker_container: Optional[str] = None

        def to_list(self) -> List[str]:
            compression_arg = (
                ""
                if self.compression is None or isinstance(self.compression, NoCompression)
                else f",{self.compression}"
            )

            schroot_arg = (
                "--no-schroot-profile" if self.schroot_profile is None else f"--schroot-profile={self.schroot_profile}"
            )

            docker_arg = (
                "--no-docker-container"
                if self.docker_container is None
                else f"--docker-container={self.docker_container}"
            )

            return [  # specify all relevant args explicitly so that config files may not disturb e2e tests
                "./homcc/client/main.py",
                "--log-level=DEBUG",
                "--verbose",
                f"--host={TestEndToEnd.ADDRESS}:{self.tcp_port}/1{compression_arg}",
                schroot_arg,
                docker_arg,
                "--timeout=20",
                self.compiler,
            ]

    class ClientProcess:
        """Client subprocess wrapper class for specified arguments."""

        def __init__(self, basic_arguments: TestEndToEnd.BasicClientArguments, args: List[str]):
            self.process: subprocess.Popen = subprocess.Popen(  # pylint: disable=consider-using-with
                basic_arguments.to_list() + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
            )

        def __enter__(self) -> subprocess.Popen:
            return self.process.__enter__()

        def __exit__(self, *exc):
            self.process.__exit__(*exc)

    class ServerProcess:
        """Server subprocess wrapper class for a specified TCP port"""

        def __init__(self, unused_tcp_port: int):
            self.unused_tcp_port: int = unused_tcp_port
            self.process: subprocess.Popen = subprocess.Popen(  # pylint: disable=consider-using-with
                [  # specify all relevant args explicitly so that config files may not disturb e2e tests
                    "./homcc/server/main.py",
                    f"--listen={TestEndToEnd.ADDRESS}",
                    f"--port={unused_tcp_port}",
                    "--jobs=1",
                    "--verbose",
                ],
                bufsize=TestEndToEnd.BUF_SIZE,
                encoding="utf-8",
            )

        def __enter__(self) -> subprocess.Popen:
            return self.process.__enter__()

        def __exit__(self, *exc):
            self.process.kill()
            self.process.__exit__(*exc)

    @staticmethod
    def run_client(basic_arguments: BasicClientArguments, args: List[str]) -> subprocess.CompletedProcess:
        time.sleep(0.5)  # wait in order to reduce the chance of trying to connect to an unavailable server
        try:
            return subprocess.run(
                basic_arguments.to_list() + args,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
            )
        except subprocess.CalledProcessError as err:
            print(err.stdout)  # print stdout in case of an error
            raise err

    @pytest.fixture(autouse=True)
    def delay_between_tests(self):
        yield
        time.sleep(1.5)

    @staticmethod
    def check_remote_compilation_assertions(result: subprocess.CompletedProcess):
        # make sure we actually compile at the server (and did not fall back to local compilation),
        # i.e. look at the log messages if the compilation of the file on the server side was okay
        assert result.returncode == os.EX_OK
        assert '"return_code": 0' in result.stdout
        assert "Compiling locally instead" not in result.stdout

    def cpp_end_to_end(self, basic_arguments: BasicClientArguments, additional_args: Optional[List[str]] = None):
        args: List[str] = [
            "-Iexample/include",
            "example/src/foo.cpp",
            "example/src/main.cpp",
            f"-o{self.OUTPUT}",
        ]

        if additional_args is not None:
            args = args + additional_args

        with self.ServerProcess(basic_arguments.tcp_port):
            result = self.run_client(basic_arguments, args)
            self.check_remote_compilation_assertions(result)
            executable_stdout: str = subprocess.check_output([f"./{self.OUTPUT}"], encoding="utf-8")
            assert executable_stdout == "homcc\n"

    def cpp_end_to_end_no_linking(self, basic_arguments: BasicClientArguments):
        args: List[str] = [
            "-c",
            "-Iexample/include",
            "example/src/foo.cpp",
            "example/src/main.cpp",
            f"-o{TestEndToEnd.OUTPUT}",
        ]

        with self.ServerProcess(basic_arguments.tcp_port):
            result = self.run_client(basic_arguments, args)
            self.check_remote_compilation_assertions(result)
            assert os.path.exists(self.OUTPUT)

    def cpp_end_to_end_preprocessor_side_effects(self, basic_arguments: BasicClientArguments):
        args: List[str] = [
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

        with self.ServerProcess(basic_arguments.tcp_port):
            result = self.run_client(basic_arguments, args)
            self.check_remote_compilation_assertions(result)
            assert os.path.exists("main.cpp.o")
            assert os.path.exists("main.cpp.o.d")

    def cpp_end_to_end_linking_only(
        self, basic_arguments: BasicClientArguments, additional_args: Optional[List[str]] = None
    ):
        main_args: List[str] = ["-Iexample/include", "example/src/main.cpp", "-c"]
        foo_args: List[str] = ["-Iexample/include", "example/src/foo.cpp", "-c"]
        linking_args: List[str] = ["main.o", "foo.o", f"-o{self.OUTPUT}"]

        if additional_args is not None:
            main_args = main_args + additional_args
            foo_args = foo_args + additional_args
            linking_args = linking_args + additional_args

        with self.ServerProcess(basic_arguments.tcp_port):
            main_result = self.run_client(basic_arguments, main_args)
            self.check_remote_compilation_assertions(main_result)
            assert os.path.exists("main.o")

            foo_result = self.run_client(basic_arguments, foo_args)
            self.check_remote_compilation_assertions(foo_result)
            assert os.path.exists("foo.o")

            linking_result = self.run_client(basic_arguments, linking_args)
            assert linking_result.returncode == os.EX_OK
            assert f"Linking [main.o, foo.o] to {self.OUTPUT}" in linking_result.stdout
            assert os.path.exists(self.OUTPUT)

    def cpp_end_to_end_multiple_clients_shared_host(self, basic_arguments: BasicClientArguments):
        # specify different compilation args
        main_args: List[str] = ["-Iexample/include", "example/src/main.cpp", "-c"]
        foo_args: List[str] = ["-Iexample/include", "example/src/foo.cpp", "-c"]

        stdout_main: str = ""
        stdout_foo: str = ""

        with self.ServerProcess(basic_arguments.tcp_port), self.ClientProcess(
            basic_arguments, main_args
        ) as client_process_main, self.ClientProcess(basic_arguments, foo_args) as client_process_foo:
            # collect stdouts from client processes until all terminated
            while client_process_main.poll() is None and client_process_foo.poll() is None:
                stdout_main += client_process_main.communicate()[0]
                stdout_foo += client_process_foo.communicate()[0]

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
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_gplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end(self.BasicClientArguments("g++", unused_tcp_port))

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_lzo_gplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end(self.BasicClientArguments("g++", unused_tcp_port, compression=LZO()))

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_lzma_gplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end(self.BasicClientArguments("g++", unused_tcp_port, compression=LZMA()))

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_gplusplus_no_linking(self, unused_tcp_port: int):
        self.cpp_end_to_end_no_linking(self.BasicClientArguments("g++", unused_tcp_port))

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_cpp_end_to_end_gplusplus_preprocessor_side_effects(self, unused_tcp_port: int):
        self.cpp_end_to_end_preprocessor_side_effects(self.BasicClientArguments("g++", unused_tcp_port))

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_gplusplus_linking_only(self, unused_tcp_port: int):
        self.cpp_end_to_end_linking_only(self.BasicClientArguments("g++", unused_tcp_port))

    @pytest.mark.gplusplus
    @pytest.mark.schroot
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_schroot_gplusplus(self, unused_tcp_port: int, schroot_profile: str):
        self.cpp_end_to_end(self.BasicClientArguments("g++", unused_tcp_port, schroot_profile=schroot_profile))

    @pytest.mark.gplusplus
    @pytest.mark.schroot
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_schroot_gplusplus_no_linking(self, unused_tcp_port: int, schroot_profile: str):
        self.cpp_end_to_end_no_linking(
            self.BasicClientArguments("g++", unused_tcp_port, schroot_profile=schroot_profile)
        )

    @pytest.mark.gplusplus
    @pytest.mark.schroot
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_schroot_gplusplus_linking_only(self, unused_tcp_port: int, schroot_profile: str):
        self.cpp_end_to_end_linking_only(
            self.BasicClientArguments("g++", unused_tcp_port, schroot_profile=schroot_profile)
        )

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_gplusplus_shared_host_slot(self, unused_tcp_port: int):
        self.cpp_end_to_end_multiple_clients_shared_host(self.BasicClientArguments("g++", unused_tcp_port))

    # clang++ tests
    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_clangplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end(self.BasicClientArguments("clang++", unused_tcp_port))

    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_clangplusplus_no_linking(self, unused_tcp_port: int):
        self.cpp_end_to_end_no_linking(self.BasicClientArguments("clang++", unused_tcp_port))

    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_cpp_end_to_end_clangplusplus_preprocessor_side_effects(self, unused_tcp_port: int):
        self.cpp_end_to_end_preprocessor_side_effects(self.BasicClientArguments("clang++", unused_tcp_port))

    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_clangplusplus_linking_only(self, unused_tcp_port: int):
        self.cpp_end_to_end_linking_only(self.BasicClientArguments("clang++", unused_tcp_port))

    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_clangplusplus_shared_host_slot(self, unused_tcp_port: int):
        self.cpp_end_to_end_multiple_clients_shared_host(self.BasicClientArguments("clang++", unused_tcp_port))

    @pytest.mark.gplusplus
    @pytest.mark.docker
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_docker_gplusplus(self, unused_tcp_port: int, docker_container: str):
        # -fPIC is needed because the docker-gcc image that we use in the CI runners
        # is not compatible with the Ubuntu 22 GitHub Action runners as linking fails without this option
        # see https://stackoverflow.com/q/19364969
        self.cpp_end_to_end(
            self.BasicClientArguments("g++", unused_tcp_port, docker_container=docker_container),
            additional_args=["-fPIC"],
        )

    @pytest.mark.gplusplus
    @pytest.mark.docker
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_docker_gplusplus_no_linking(self, unused_tcp_port: int, docker_container: str):
        self.cpp_end_to_end_no_linking(
            self.BasicClientArguments("g++", unused_tcp_port, docker_container=docker_container)
        )

    @pytest.mark.gplusplus
    @pytest.mark.docker
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_docker_gplusplus_linking_only(self, unused_tcp_port: int, docker_container: str):
        self.cpp_end_to_end_linking_only(
            self.BasicClientArguments("g++", unused_tcp_port, docker_container=docker_container),
            additional_args=["-fPIC"],
        )
