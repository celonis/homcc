"""Tests for the server environment."""
from homcc.server.environment import map_arguments, map_cwd, extract_source_files


class TestServerEnvironment:
    """Tests the server environment."""

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
