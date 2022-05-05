"""Tests for the server environment."""
from pytest_mock.plugin import MockerFixture
import pytest
from pathlib import Path

from homcc.common.compression import NoCompression
from homcc.server.environment import CompilerResult, Environment
from homcc.server.cache import Cache


def create_mock_environment(instance_folder: str, mapped_cwd: str) -> Environment:
    Environment.__init__ = lambda *_: None  # type: ignore
    Environment.__del__ = lambda *_: None  # type: ignore
    environment = Environment(Path(), "")

    environment.instance_folder = instance_folder
    environment.mapped_cwd = mapped_cwd

    return environment


class TestServerEnvironment:
    """Tests the server environment."""

    def test_map_arguments(self):
        arguments = [
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
        mapped_arguments = environment.map_arguments(arguments)

        assert mapped_arguments.pop(0) == "gcc"
        assert mapped_arguments.pop(0) == f"-I{environment.mapped_cwd}/relative_path/relative.h"
        assert mapped_arguments.pop(0) == f"-I{environment.instance_folder}/var/includes/absolute.h"
        assert mapped_arguments.pop(0) == f"-I{environment.instance_folder}/var/includes/absolute.h"
        assert mapped_arguments.pop(0) == f"-isysroot{environment.instance_folder}/var/lib/sysroot.h"
        assert mapped_arguments.pop(0) == f"-o{environment.instance_folder}/home/user/output.o"
        assert mapped_arguments.pop(0) == f"-isystem{environment.instance_folder}/var/lib/system.h"
        assert mapped_arguments.pop(0) == f"{environment.mapped_cwd}/main.cpp"
        assert mapped_arguments.pop(0) == f"{environment.mapped_cwd}/relative/relative.cpp"
        assert mapped_arguments.pop(0) == f"{environment.instance_folder}/opt/src/absolute.cpp"

    def test_map_arguments_relative_paths(self):
        arguments = [
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
        mapped_arguments = environment.map_arguments(arguments)

        assert mapped_arguments.pop(0) == "gcc"
        assert mapped_arguments.pop(0) == "-BsomeOtherArgument"
        assert mapped_arguments.pop(0) == "-FooArgument"
        assert mapped_arguments.pop(0) == "should_not_be_mapped"
        assert mapped_arguments.pop(0) == f"-o{environment.mapped_cwd}/output_folder/b.out"
        assert mapped_arguments.pop(0) == "-I/client1/test/abc/include/foo.h"
        assert mapped_arguments.pop(0) == f"-I{environment.mapped_cwd}/include/foo2.h"
        assert mapped_arguments.pop(0) == "-isystem/client1/include/sys.h"
        assert mapped_arguments.pop(0) == "/client1/test/main.cpp"
        assert mapped_arguments.pop(0) == f"{environment.mapped_cwd}/relative.cpp"
        assert mapped_arguments.pop(0) == "-c"
        assert mapped_arguments.pop(0) == f"{environment.mapped_cwd}/some_file.cpp"

    def test_map_cwd(self):
        instance_path = "/client1/"
        cwd = "/home/xyz/query-engine"

        environment = create_mock_environment(instance_path, cwd)
        mapped_cwd = environment.map_cwd(cwd)

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
        mocked_compiler_result = CompilerResult(0, "", "")
        mocker.patch(
            "homcc.server.environment.Environment.invoke_compiler",
            return_value=mocked_compiler_result,
        )
        mocker.patch("pathlib.Path.read_bytes", return_value=bytes())

    def test_multiple_files(self):
        instance_path = "/tmp/homcc/test-id"
        mapped_cwd = "/tmp/homcc/test-id/home/user/cwd"
        arguments = [
            "gcc",
            "-I../abc/include/foo.h",
            f"{mapped_cwd}/src/main.cpp",
            f"{mapped_cwd}/other.cpp",
        ]

        environment = create_mock_environment(instance_path, mapped_cwd)
        result_message = environment.do_compilation(arguments, NoCompression())

        assert len(result_message.object_files) == 2
        assert result_message.object_files[0].file_name == "/home/user/cwd/main.o"
        assert result_message.object_files[1].file_name == "/home/user/cwd/other.o"

    def test_single_file(self):
        instance_path = "/tmp/homcc/test-id"
        mapped_cwd = "/tmp/homcc/test-id/home/user/cwd"
        arguments = [
            "gcc",
            "-I../abc/include/foo.h",
            f"{mapped_cwd}/src/this_is_a_source_file.cpp",
        ]

        environment = create_mock_environment(instance_path, mapped_cwd)
        result_message = environment.do_compilation(arguments, NoCompression())

        assert len(result_message.object_files) == 1
        assert result_message.object_files[0].file_name == "/home/user/cwd/this_is_a_source_file.o"
