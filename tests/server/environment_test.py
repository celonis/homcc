from pytest_mock.plugin import MockerFixture
import pytest

from homcc.server.environment import (
    CompilerResult,
    map_arguments,
    map_cwd,
    _unmap_path,
    extract_source_files,
    get_output_path,
    do_compilation,
)


class TestServerEnvironmentPathMapping:
    """Tests the server environment path mappings."""

    def test_map_arguments(self):
        instance_path = "/client1"
        mapped_cwd = "/client1/test/xyz"

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

        mapped_arguments = map_arguments(instance_path, mapped_cwd, arguments)

        assert mapped_arguments.pop(0) == "gcc"
        assert mapped_arguments.pop(0) == f"-I{mapped_cwd}/relative_path/relative.h"
        assert mapped_arguments.pop(0) == f"-I{instance_path}/var/includes/absolute.h"
        assert mapped_arguments.pop(0) == "-I"
        assert mapped_arguments.pop(0) == f"{instance_path}/var/includes/absolute.h"
        assert mapped_arguments.pop(0) == f"-isysroot{instance_path}/var/lib/sysroot.h"
        assert mapped_arguments.pop(0) == f"-o{instance_path}/home/user/output.o"
        assert mapped_arguments.pop(0) == f"-isystem{instance_path}/var/lib/system.h"
        assert mapped_arguments.pop(0) == f"{mapped_cwd}/main.cpp"
        assert mapped_arguments.pop(0) == f"{mapped_cwd}/relative/relative.cpp"
        assert mapped_arguments.pop(0) == f"{instance_path}/opt/src/absolute.cpp"

    def test_map_arguments_relative_paths(self):
        instance_path = "/client1"
        mapped_cwd = "/client1/test/xyz"

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
        ]

        mapped_arguments = map_arguments(instance_path, mapped_cwd, arguments)

        assert mapped_arguments.pop(0) == "gcc"
        assert mapped_arguments.pop(0) == "-BsomeOtherArgument"
        assert mapped_arguments.pop(0) == "-FooArgument"
        assert mapped_arguments.pop(0) == "should_not_be_mapped"
        assert mapped_arguments.pop(0) == "-o"
        assert mapped_arguments.pop(0) == f"{mapped_cwd}/output_folder/b.out"
        assert mapped_arguments.pop(0) == "-I/client1/test/abc/include/foo.h"
        assert mapped_arguments.pop(0) == f"-I{mapped_cwd}/include/foo2.h"
        assert mapped_arguments.pop(0) == "-isystem"
        assert mapped_arguments.pop(0) == "/client1/include/sys.h"
        assert mapped_arguments.pop(0) == "/client1/test/main.cpp"
        assert mapped_arguments.pop(0) == f"{mapped_cwd}/relative.cpp"

    def test_map_cwd(self):
        instance_path = "/client1/"
        cwd = "/home/xyz/query-engine"

        mapped_cwd = map_cwd(instance_path, cwd)

        assert mapped_cwd == "/client1/home/xyz/query-engine"

    def test_unmap(self):
        instance_path = "/tmp/homcc-random/"

        client_path = "/home/user/output/a.out"
        mapped_path = f"{instance_path}/{client_path}"

        unmapped = _unmap_path(instance_path, mapped_path)

        assert unmapped == client_path

    def test_get_output_path_separated(self):
        arguments = ["gcc", "-Iabc.h", "-o", "cwd/test.o", "foo.c"]
        source_file_name = "foo.c"

        output_path = get_output_path("cwd", source_file_name, arguments)
        assert output_path == "cwd/test.o"

    def test_get_output_path_together(self):
        arguments = ["gcc", "-Iabc.h", "-ocwd/another_test.o", "foo.c"]
        source_file_name = "foo.c"

        output_path = get_output_path("cwd", source_file_name, arguments)
        assert output_path == "cwd/another_test.o"

    def test_get_output_path_default(self):
        arguments = ["gcc", "-Iabc.h", "-O2", "foo.c"]
        source_file_name = "foo.c"

        output_path = get_output_path("cwd", source_file_name, arguments)
        assert output_path == "cwd/foo.o"

    def test_extract_source_files(self):
        source_file_arguments = [
            "main.cpp",
            "relative/relative.cpp",
            "/opt/src/absolute.cpp",
        ]
        arguments = [
            "gcc",
            "-Irelative_path/relative.h",
            "-I",
            "/var/includes/absolute.h",
        ] + source_file_arguments

        assert extract_source_files(arguments) == source_file_arguments

    def test_extract_source_files_simple(self):
        source_file_arguments = ["some/relative/path.c"]
        arguments = [
            "gcc",
            "-O3",
        ] + source_file_arguments

        assert extract_source_files(arguments) == source_file_arguments

    def test_extract_single_source_file(self):
        source_file_arguments = ["some/relative/path.c"]
        arguments = [
            "gcc",
            "-o/output/out.o",
        ] + source_file_arguments

        assert extract_source_files(arguments) == source_file_arguments


class TestServerCompilation:
    """Tests the server compilation process."""

    @pytest.fixture(autouse=True)
    def setup_mocks(self, mocker: MockerFixture):
        mocked_compiler_result = CompilerResult(0, "", "")
        mocker.patch(
            "homcc.server.environment.invoke_compiler",
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

        result_message = do_compilation(instance_path, mapped_cwd, arguments)

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

        result_message = do_compilation(instance_path, mapped_cwd, arguments)

        assert len(result_message.object_files) == 1
        assert (
            result_message.object_files[0].file_name
            == "/home/user/cwd/this_is_a_source_file.o"
        )

    def test_single_file_output_argument(self):
        instance_path = "/tmp/homcc/test-id"
        mapped_cwd = "/tmp/homcc/test-id/home/user/cwd"
        arguments = [
            "gcc",
            "-I../abc/include/foo.h",
            f"-o{mapped_cwd}/output/out.o",
            f"{mapped_cwd}/src/this_is_a_source_file.cpp",
        ]

        result_message = do_compilation(instance_path, mapped_cwd, arguments)

        assert len(result_message.object_files) == 1
        assert result_message.object_files[0].file_name == "/home/user/cwd/output/out.o"
