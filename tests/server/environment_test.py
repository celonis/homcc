"""Tests for the server environment."""
from pytest_mock.plugin import MockerFixture
import pytest
import shutil
from pathlib import Path

from homcc.common.compression import NoCompression
from homcc.server.environment import ArgumentsExecutionResult, Environment
from homcc.server.cache import Cache
from homcc.common.arguments import Arguments


def create_mock_environment(instance_folder: str, mapped_cwd: str) -> Environment:
    Environment.__init__ = lambda *_: None  # type: ignore
    Environment.__del__ = lambda *_: None  # type: ignore
    environment = Environment(Path(), "", None, NoCompression())

    environment.instance_folder = instance_folder
    environment.mapped_cwd = mapped_cwd
    environment.profile = None
    environment.compression = NoCompression()

    return environment


class TestServerEnvironment:
    """Tests the server environment."""

    def test_map_arguments(self):
        args = [
            "gcc",
            "-Irelative_path/relative.h",
            "-I/var/includes/absolute.h",
            "-I",
            "/var/includes/absolute.h",
            "-isysroot/var/lib/sysroot.h",
            "-o/home/user/output.o",
            "-isystem/var/lib/system.h",
            "main.cpp",
            "relative/relative.cpp",
            "/opt/src/absolute.cpp",
        ]
        environment = create_mock_environment("/client1", "/client1/test/xyz")
        mapped_args = list(environment.map_args(args))

        assert mapped_args.pop(0) == "gcc"
        assert mapped_args.pop(0) == f"-I{environment.mapped_cwd}/relative_path/relative.h"
        assert mapped_args.pop(0) == f"-I{environment.instance_folder}/var/includes/absolute.h"
        assert mapped_args.pop(0) == f"-I{environment.instance_folder}/var/includes/absolute.h"
        assert mapped_args.pop(0) == f"-isysroot{environment.instance_folder}/var/lib/sysroot.h"
        assert mapped_args.pop(0) == f"-o{environment.instance_folder}/home/user/output.o"
        assert mapped_args.pop(0) == f"-isystem{environment.instance_folder}/var/lib/system.h"
        assert mapped_args.pop(0) == f"{environment.mapped_cwd}/main.cpp"
        assert mapped_args.pop(0) == f"{environment.mapped_cwd}/relative/relative.cpp"
        assert mapped_args.pop(0) == f"{environment.instance_folder}/opt/src/absolute.cpp"

    def test_map_arguments_relative_paths(self):
        args = [
            "gcc",
            "-BsomeOtherArgument",
            "-FooArgument",
            "should_not_be_mapped",
            "-o",
            "output_folder/b.out",
            "-I../abc/include/foo.h",
            "-I./include/foo2.h",
            "-isystem",
            ".././../include/sys.h",
            "../main.cpp",
            "./relative.cpp",
            "-c",
            "some_file.cpp",
        ]

        environment = create_mock_environment("/client1", "/client1/test/xyz")
        mapped_args = list(environment.map_args(args))

        assert mapped_args.pop(0) == "gcc"
        assert mapped_args.pop(0) == "-BsomeOtherArgument"
        assert mapped_args.pop(0) == "-FooArgument"
        assert mapped_args.pop(0) == "should_not_be_mapped"
        assert mapped_args.pop(0) == f"-o{environment.mapped_cwd}/output_folder/b.out"
        assert mapped_args.pop(0) == "-I/client1/test/abc/include/foo.h"
        assert mapped_args.pop(0) == f"-I{environment.mapped_cwd}/include/foo2.h"
        assert mapped_args.pop(0) == "-isystem/client1/include/sys.h"
        assert mapped_args.pop(0) == "/client1/test/main.cpp"
        assert mapped_args.pop(0) == f"{environment.mapped_cwd}/relative.cpp"
        assert mapped_args.pop(0) == "-c"
        assert mapped_args.pop(0) == f"{environment.mapped_cwd}/some_file.cpp"

    def test_map_cwd(self):
        instance_path = "/client1/"
        cwd = "/home/xyz/query-engine"

        environment = create_mock_environment(instance_folder="", mapped_cwd="")
        mapped_cwd = environment.map_cwd(cwd, instance_path)

        assert mapped_cwd == "/client1/home/xyz/query-engine"

    def test_unmap(self):
        instance_path = "/tmp/homcc-random/"
        environment = create_mock_environment(instance_path, "")

        client_path = "/home/user/output/a.out"
        mapped_path = f"{instance_path}/{client_path}"

        unmapped = environment.unmap_path(mapped_path)

        assert unmapped == client_path

    def test_caching(self, mocker: MockerFixture):
        dependencies = {"file1": "hash1", "file2": "hash2", "file3": "hash3"}
        mocker.patch(
            "os.link",
        )

        # mock the locks
        lock_mock = mocker.Mock()
        lock_mock.__enter__ = mocker.Mock(return_value=(mocker.Mock(), None))
        lock_mock.__exit__ = mocker.Mock(return_value=None)

        environment = create_mock_environment("", "")
        # pylint: disable=protected-access
        Cache._create_cache_folder = lambda *_: None  # type: ignore
        cache = Cache(Path(""))
        cache.cache = {"hash2": "some/path/to/be/linked"}

        needed_dependencies = environment.get_needed_dependencies(dependencies, cache)

        assert len(needed_dependencies) == 2
        assert "file1" in needed_dependencies
        assert "file3" in needed_dependencies


class TestServerCompilation:
    """Tests the server compilation process."""

    @pytest.fixture(autouse=True)
    def setup_mocks(self, mocker: MockerFixture):
        mocked_compiler_result = ArgumentsExecutionResult(0, "", "")
        mocker.patch(
            "homcc.server.environment.Environment.invoke_compiler",
            return_value=mocked_compiler_result,
        )
        mocker.patch("pathlib.Path.read_bytes", return_value=bytes())

    def test_multiple_files(self):
        instance_path = "/tmp/homcc/test-id"
        mapped_cwd = "/tmp/homcc/test-id/home/user/cwd"
        arguments = Arguments.from_args(
            [
                "gcc",
                "-I../abc/include/foo.h",
                f"{mapped_cwd}/src/main.cpp",
                f"{mapped_cwd}/other.cpp",
            ]
        )

        environment = create_mock_environment(instance_path, mapped_cwd)
        result_message = environment.do_compilation(arguments)

        assert len(result_message.object_files) == 2
        assert result_message.object_files[0].file_name == "/home/user/cwd/main.o"
        assert result_message.object_files[1].file_name == "/home/user/cwd/other.o"

    def test_single_file(self):
        instance_path = "/tmp/homcc/test-id"
        mapped_cwd = "/tmp/homcc/test-id/home/user/cwd"
        arguments = Arguments.from_args(
            [
                "gcc",
                "-I../abc/include/foo.h",
                f"{mapped_cwd}/src/this_is_a_source_file.cpp",
            ]
        )

        environment = create_mock_environment(instance_path, mapped_cwd)
        result_message = environment.do_compilation(arguments)

        assert len(result_message.object_files) == 1
        assert result_message.object_files[0].file_name == "/home/user/cwd/this_is_a_source_file.o"

    def test_debug_symbol_mappings(self, mocker: MockerFixture):
        invoke_compiler_mock = mocker.patch(
            "homcc.server.environment.Environment.invoke_compiler",
        )

        instance_path = "/tmp/homcc/test-id"
        mapped_cwd = "/tmp/homcc/test-id/home/user/cwd"
        environment = create_mock_environment(instance_path, mapped_cwd)

        debug_arguments = Arguments.from_args(
            [
                "gcc",
                "-g",
                f"{mapped_cwd}/src/foo.cpp",
            ]
        )
        environment.do_compilation(debug_arguments)

        # ensure that we call the compiler with an instruction to remap the debug symbols
        passed_debug_arguments: Arguments = invoke_compiler_mock.call_args_list[0].args[0]
        assert f"-fdebug-prefix-map={instance_path}=" in passed_debug_arguments.args

        no_debug_arguments = Arguments.from_args(
            [
                "gcc",
                f"{mapped_cwd}/src/foo.cpp",
            ]
        )
        environment.do_compilation(no_debug_arguments)

        # ensure that the flag is not passed to the compiler when not compiling with debug symbols
        passed_no_debug_arguments: Arguments = invoke_compiler_mock.call_args_list[1].args[0]
        assert "-fdebug-prefix-map" not in str(passed_no_debug_arguments.args)

    @pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
    def test_compiler_exists(self):
        gpp_arguments = Arguments.from_args(["g++", "do_something"])
        assert Environment.compiler_exists(gpp_arguments)

        non_existing_compiler_arguments = Arguments.from_args(["non-existing-compiler", "do_something"])
        assert not Environment.compiler_exists(non_existing_compiler_arguments)
