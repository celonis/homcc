"""End to end integration tests, testing both the client and the server."""
from __future__ import annotations

import os
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import pytest

from homcc.common.compression import LZMA, LZO, Compression, NoCompression
from homcc.common.constants import ENCODING


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
        compression: Compression = NoCompression()
        schroot_profile: Optional[str] = None
        docker_container: Optional[str] = None

        def __post_init__(self):
            if self.schroot_profile is not None and self.docker_container is not None:
                raise NotImplementedError("schroot profile and docker container are provided simultaneously")

        def __iter__(self) -> Iterator[str]:
            compression = (
                f",{self.compression}" if self.compression is not isinstance(self.compression, NoCompression) else ""
            )
            host_arg = f"--host={TestEndToEnd.ADDRESS}:{self.tcp_port}/1{compression}"  # explicit host limit: 1

            sandbox_arg: str = "--no-sandbox"

            if self.schroot_profile is not None:
                sandbox_arg = f"--schroot-profile={self.schroot_profile}"
            elif self.docker_container is not None:
                sandbox_arg = f"--docker-container={self.docker_container}"

            yield from (
                "./homcc/client/main.py",
                "--no-config",  # disable external configuration
                "--verbose",  # required for assertions on stdout
                host_arg,
                sandbox_arg,
                self.compiler,
            )

    class ClientProcess:
        """Client subprocess wrapper class for specified arguments."""

        def __init__(self, basic_arguments: TestEndToEnd.BasicClientArguments, args: List[str]):
            self.process: subprocess.Popen = subprocess.Popen(  # pylint: disable=consider-using-with
                list(basic_arguments) + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding=ENCODING,
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
                [
                    "./homcc/server/main.py",
                    "--no-config",  # disable external configuration
                    "--verbose",  # required for assertions on stdout
                    f"--listen={TestEndToEnd.ADDRESS}",
                    f"--port={unused_tcp_port}",
                    "--jobs=1",
                ],
                bufsize=TestEndToEnd.BUF_SIZE,
                encoding=ENCODING,
            )

        def __enter__(self) -> subprocess.Popen:
            return self.process.__enter__()

        def __exit__(self, *exc):
            self.process.kill()
            self.process.__exit__(*exc)

    @staticmethod
    def run_client(args: List[str]) -> subprocess.CompletedProcess:
        time.sleep(0.5)  # wait in order to reduce the chance of trying to connect to an unavailable server

        try:
            return subprocess.run(
                args,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding=ENCODING,
            )
        except subprocess.CalledProcessError as err:
            time.sleep(0.5)  # wait to reduce interference with server logging
            sys.stdout.write(err.stdout)
            raise err

    @pytest.fixture(autouse=True)
    def delay_between_tests(self):
        yield
        time.sleep(1.5)

    @staticmethod
    def check_local_fallback_compilation_assertions(result: subprocess.CompletedProcess):
        # make sure we did not compile at the server and fell back to local compilation,
        # i.e. look at the log messages if the compilation of the file was not performed on the server side
        assert result.returncode == os.EX_OK
        assert "Compiling locally instead" in result.stdout

    @staticmethod
    def check_remote_compilation_assertions(result: subprocess.CompletedProcess):
        # make sure we actually compile at the server (and did not fall back to local compilation),
        # i.e. look at the log messages if the compilation of the file on the server side was okay
        assert result.returncode == os.EX_OK
        assert '"return_code": 0' in result.stdout
        assert "Compiling locally instead" not in result.stdout

    def cpp_end_to_end(self, basic_arguments: BasicClientArguments):
        args: List[str] = [
            "-Iexample/include",
            "example/src/foo.cpp",
            "example/src/main.cpp",
            f"-o{self.OUTPUT}",
        ]

        with self.ServerProcess(basic_arguments.tcp_port):
            result = self.run_client(list(basic_arguments) + args)
            self.check_remote_compilation_assertions(result)
            executable_stdout: str = subprocess.check_output([f"./{self.OUTPUT}"], encoding=ENCODING)
            assert executable_stdout == "homcc\n"

    def cpp_end_to_end_no_linking(self, basic_arguments: BasicClientArguments):
        args: List[str] = [
            "-c",
            "-Iexample/include",
            "example/src/foo.cpp",
            "example/src/main.cpp",
        ]

        with self.ServerProcess(basic_arguments.tcp_port):
            result = self.run_client(list(basic_arguments) + args)
            self.check_remote_compilation_assertions(result)
            assert os.path.exists("main.o")
            assert os.path.exists("foo.o")

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
            result = self.run_client(list(basic_arguments) + args)
            self.check_remote_compilation_assertions(result)
            assert os.path.exists("main.cpp.o")
            assert os.path.exists("main.cpp.o.d")

    def cpp_end_to_end_linking_only(self, basic_arguments: BasicClientArguments):
        main_args: List[str] = ["-Iexample/include", "example/src/main.cpp", "-c"]
        foo_args: List[str] = ["-Iexample/include", "example/src/foo.cpp", "-c"]
        linking_args: List[str] = ["main.o", "foo.o", f"-o{self.OUTPUT}"]

        with self.ServerProcess(basic_arguments.tcp_port):
            main_result = self.run_client(list(basic_arguments) + main_args)
            self.check_remote_compilation_assertions(main_result)
            assert os.path.exists("main.o")

            foo_result = self.run_client(list(basic_arguments) + foo_args)
            self.check_remote_compilation_assertions(foo_result)
            assert os.path.exists("foo.o")

            linking_result = self.run_client(list(basic_arguments) + linking_args)
            assert linking_result.returncode == os.EX_OK
            assert f"is linking-only to '{self.OUTPUT}'" in linking_result.stdout
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

    def cpp_end_to_end_implicit_compiler(self, compiler: str, unused_tcp_port: int):
        # symlink compiler to homcc and make it executable, so we implicitly call the actual specified compiler
        shadow_compiler: Path = Path.cwd() / f"homcc/client/{compiler}"
        shadow_compiler.symlink_to(Path.cwd() / "homcc/client/main.py")
        shadow_compiler.chmod(shadow_compiler.stat().st_mode | stat.S_IEXEC)
        assert shadow_compiler.exists()

        env: Dict[str, str] = os.environ.copy()
        env["HOMCC_HOSTS"] = f"127.0.0.1:{unused_tcp_port}/1"
        env["HOMCC_VERBOSE"] = "True"

        args: List[str] = [
            str(shadow_compiler),
            "-Iexample/include",
            "example/src/foo.cpp",
            "example/src/main.cpp",
            f"-o{self.OUTPUT}",
        ]

        # local compilation fallback
        result = subprocess.run(
            args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding=ENCODING,
            env=env,
        )
        self.check_local_fallback_compilation_assertions(result)

        # successful remote compilation
        with self.ServerProcess(unused_tcp_port):
            time.sleep(0.5)  # wait in order to reduce the chance of trying to connect to an unavailable server
            result = subprocess.run(
                args,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding=ENCODING,
                env=env,
            )
            self.check_remote_compilation_assertions(result)

    def cpp_end_to_end_fission(self, basic_arguments: BasicClientArguments, with_linking: bool):
        additional_client_args: List[str] = [
            "-Iexample/include",
            "example/src/foo.cpp",
            "example/src/main.cpp",
            "-gsplit-dwarf",
            "-g",
        ]

        if not with_linking:
            additional_client_args.append("-c")

        with self.ServerProcess(basic_arguments.tcp_port):
            result = self.run_client(list(basic_arguments) + additional_client_args)
            self.check_remote_compilation_assertions(result)

            if with_linking:
                assert os.path.exists("a.out")
            else:
                assert os.path.exists("foo.o")
                assert os.path.exists("main.o")

            assert os.path.exists("foo.dwo")
            assert os.path.exists("main.dwo")

    @pytest.fixture(autouse=True)
    def clean_up(self):
        yield
        Path("main.o").unlink(missing_ok=True)
        Path("main.cpp.o").unlink(missing_ok=True)
        Path("main.cpp.o.d").unlink(missing_ok=True)
        Path("foo.o").unlink(missing_ok=True)
        Path(self.OUTPUT).unlink(missing_ok=True)
        Path("homcc/client/clang-homcc").unlink(missing_ok=True)  # test_end_to_end_client_recursive
        Path("homcc/client/g++").unlink(missing_ok=True)  # test_end_to_end_implicit_gplusplus
        Path("homcc/client/clang++").unlink(missing_ok=True)  # test_end_to_end_implicit_clangplusplus
        Path("a.out").unlink(missing_ok=True)  # cpp_end_to_end_fission
        Path("a-foo.dwo").unlink(missing_ok=True)  # cpp_end_to_end_fission
        Path("a-main.dwo").unlink(missing_ok=True)  # cpp_end_to_end_fission
        Path("foo.dwo").unlink(missing_ok=True)  # cpp_end_to_end_fission
        Path("main.dwo").unlink(missing_ok=True)  # cpp_end_to_end_fission

    # client failures
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_client_recursive(self, unused_tcp_port: int):
        # symlink clang-homcc to homcc and make it executable in order for it to be viewed as a "regular" clang compiler
        # the mocked compiler needs to be in the same folder as the original script in order for imports to work
        mock_compiler: Path = Path.cwd() / "homcc/client/clang-homcc"
        mock_compiler.symlink_to(Path.cwd() / "homcc/client/main.py")
        mock_compiler.chmod(mock_compiler.stat().st_mode | stat.S_IEXEC)
        assert mock_compiler.exists()

        basic_arguments: TestEndToEnd.BasicClientArguments = self.BasicClientArguments(
            str(mock_compiler), unused_tcp_port
        )
        args: List[str] = ["-Iexample/include", "example/src/foo.cpp", "example/src/main.cpp", f"-o{self.OUTPUT}"]

        # fail scan_includes during dependency finding (not e2e)
        with pytest.raises(subprocess.CalledProcessError) as scan_includes_err:
            scan_includes_args = list(basic_arguments)
            scan_includes_args.insert(1, "--scan-includes")
            self.run_client(scan_includes_args + args)

        assert "has been invoked recursively!" in scan_includes_err.value.stdout

        # fail during local compilation fallback since server was not started
        with pytest.raises(subprocess.CalledProcessError) as local_err:
            self.run_client(list(basic_arguments) + args)

        assert "Compiling locally instead" in local_err.value.stdout
        assert "has been invoked recursively!" in local_err.value.stdout

        # fail remote compilation during dependency finding after having connected to the server
        with self.ServerProcess(basic_arguments.tcp_port), pytest.raises(
            subprocess.CalledProcessError
        ) as try_remote_err:
            self.run_client(list(basic_arguments) + args)

        assert "Compiling locally instead" not in try_remote_err.value.stdout
        assert "has been invoked recursively!" in try_remote_err.value.stdout

    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_client_multiple_sandbox(self, unused_tcp_port: int):
        env: Dict[str, str] = os.environ.copy()
        env["HOMCC_DOCKER_CONTAINER"] = "bar"

        with pytest.raises(subprocess.CalledProcessError) as err:
            subprocess.run(  # client receiving multiple sandbox options
                list(self.BasicClientArguments("g++", unused_tcp_port, schroot_profile="foo")),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding=ENCODING,
                env=env,
            )

        assert err.value.returncode == os.EX_USAGE
        assert "Can not specify a schroot profile and a docker container to be used simultaneously." in err.value.stdout

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
    def test_end_to_end_implicit_gplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end_implicit_compiler("g++", unused_tcp_port)

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_gplusplus_shared_host_slot(self, unused_tcp_port: int):
        self.cpp_end_to_end_multiple_clients_shared_host(self.BasicClientArguments("g++", unused_tcp_port))

    @pytest.mark.gplusplus
    @pytest.mark.docker
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_docker_gplusplus(self, unused_tcp_port: int, docker_container: str):
        self.cpp_end_to_end(self.BasicClientArguments("g++", unused_tcp_port, docker_container=docker_container))

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
            self.BasicClientArguments("g++", unused_tcp_port, docker_container=docker_container)
        )

    def test_print_compilation_stages_gplusplus(self):
        # homcc --verbose g++ -v; even with explicit verbose enabled, logging should not interfere
        homcc_result: subprocess.CompletedProcess = subprocess.run(
            ["./homcc/client/main.py", "--verbose", "--host=127.0.0.1/1", "g++", "-v"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding=ENCODING,
        )

        # g++ -v
        gplusplus_result: subprocess.CompletedProcess = subprocess.run(
            ["g++", "-v"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding=ENCODING,
        )

        assert homcc_result.returncode == os.EX_OK
        assert gplusplus_result.returncode == os.EX_OK
        assert homcc_result.stdout == gplusplus_result.stdout

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_gplusplus_fission_no_linking(self, unused_tcp_port: int):
        self.cpp_end_to_end_fission(self.BasicClientArguments("g++", unused_tcp_port), with_linking=False)

    @pytest.mark.gplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_gplusplus_fission_with_linking(self, unused_tcp_port: int):
        self.cpp_end_to_end_fission(self.BasicClientArguments("g++", unused_tcp_port), with_linking=True)

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
    def test_end_to_end_implicit_clangplusplus(self, unused_tcp_port: int):
        self.cpp_end_to_end_implicit_compiler("clang++", unused_tcp_port)

    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_clangplusplus_shared_host_slot(self, unused_tcp_port: int):
        self.cpp_end_to_end_multiple_clients_shared_host(self.BasicClientArguments("clang++", unused_tcp_port))

    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_print_compilation_stages_clangplusplus(self):
        # homcc --verbose clang++ -v; even with explicit verbose enabled, logging should not interfere
        homcc_result: subprocess.CompletedProcess = subprocess.run(
            ["./homcc/client/main.py", "--verbose", "--host=127.0.0.1/1", "clang++", "-v"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding=ENCODING,
        )

        # clang++ -v
        clangplusplus_result: subprocess.CompletedProcess = subprocess.run(
            ["clang++", "-v"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding=ENCODING,
        )

        assert homcc_result.returncode == os.EX_OK
        assert clangplusplus_result.returncode == os.EX_OK
        assert homcc_result.stdout == clangplusplus_result.stdout

    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_clangplusplus_fission_no_linking(self, unused_tcp_port: int):
        self.cpp_end_to_end_fission(self.BasicClientArguments("clang++", unused_tcp_port), with_linking=False)

    @pytest.mark.clangplusplus
    @pytest.mark.timeout(TIMEOUT)
    def test_end_to_end_clangplusplus_fission_with_linking(self, unused_tcp_port: int):
        self.cpp_end_to_end_fission(self.BasicClientArguments("clang++", unused_tcp_port), with_linking=True)
