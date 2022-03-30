"""Tests regarding the arguments module of homcc."""
import pytest

from shutil import which
from typing import Dict, List, Optional

from homcc.common.arguments import Arguments, ArgumentsOutputError


class TestArguments:
    """Tests for common/arguments.py"""

    def test_is_source_file(self):
        source_files: List[str] = ["foo.c", "bar.cpp"]
        for source_file in source_files:
            assert Arguments.is_source_file(source_file)

        not_source_files: List[str] = ["", ".", ".cpp", "foo.hpp"]
        for not_source_file in not_source_files:
            assert not Arguments.is_source_file(not_source_file)

    def test_is_object_file(self):
        object_file: str = "foo.o"
        assert Arguments.is_object_file(object_file)

        not_object_files: List[str] = ["", ".", ".o"]
        for not_object_file in not_object_files:
            assert not Arguments.is_object_file(not_object_file)

    def test_is_executable(self):
        # these executables should be present on most platforms
        executables: List[str] = list(filter(lambda exe: which(exe) is not None, ["cd", "echo", "time"]))

        if not executables:
            assert not "No executables to test"

        for executable in executables:
            assert Arguments.is_executable(executable)

    def test_is_compiler(self):
        compilers: List[str] = list(
            filter(lambda _compiler: which(_compiler) is not None, ["cc", "gcc", "g++", "clang", "clang++"])
        )

        if not compilers:
            assert not "No compilers installed to test"

        for compiler in compilers:
            assert Arguments.is_compiler(compiler)

    def test_test_from_argv(self):
        specified_compiler_args: List[str] = ["homcc_client.py", "g++", "-c", "foo.cpp"]
        assert Arguments.from_argv(specified_compiler_args) == specified_compiler_args[1:]

        unspecified_compiler_args: List[str] = ["homcc_client.py", "-c", "foo.cpp"]
        assert Arguments.from_argv(unspecified_compiler_args, "g++") == specified_compiler_args[1:]

    def test_is_sendable(self):
        sendable_args: List[str] = ["g++", "foo.cpp", "-ofoo"]
        assert Arguments(sendable_args).is_sendable()

        preprocessor_args: List[str] = ["g++", "foo.cpp", "-E"]
        assert not Arguments(preprocessor_args).is_sendable()

        no_assembly_args: List[str] = ["g++", "foo.cpp", "-S"]
        assert not Arguments(no_assembly_args).is_sendable()

    def test_is_linking(self):
        linking_args: List[str] = ["g++", "foo.cpp", "-ofoo"]
        assert Arguments(linking_args).is_linking()

        not_linking_args: List[str] = ["g++", "foo.cpp", "-c"]
        assert not Arguments(not_linking_args).is_linking()

    def test_output_target(self):
        args: List[str] = ["g++", "foo.cpp", "-O0"]
        assert Arguments(args).output is None

        single_output_args: List[str] = args + ["-o", "foo"]
        assert Arguments(single_output_args).output == "foo"

        multiple_output_args: List[str] = args + ["-o", "foo", "-o", "bar"]
        assert Arguments(multiple_output_args).output == "bar"

        mixed_output_args: List[str] = args + ["-o", "foo", "-obar"]
        assert Arguments(mixed_output_args).output == "bar"

        output_flag_as_output_args: List[str] = args + ["-ofoo", "-o", "-o"]
        assert Arguments(output_flag_as_output_args).output == "-o"

        long_output_path_args: List[str] = args + ["-o", "long/path/to/output"]
        assert Arguments(long_output_path_args).output == "long/path/to/output"

        # failing output extraction as 2nd output argument has no specified target
        with pytest.raises(ArgumentsOutputError):
            ill_formed_output_args: List[str] = args + ["-ofoo", "-o"]
            _: Optional[str] = Arguments(ill_formed_output_args).output
            assert False

    def test_add_output_arg(self):
        output: str = "foo"

        args: List[str] = ["g++", "foo.cpp", "-O0"]
        arguments: Arguments = Arguments(args)
        arguments.output = output
        assert arguments.output == output

        multiple_output_args: List[str] = args + ["-o", "foo", "-o", "bar"]
        multiple_output_arguments: Arguments = Arguments(multiple_output_args)
        assert multiple_output_arguments.output == "bar"
        multiple_output_arguments.output = output
        assert multiple_output_arguments.output == output

    def test_remove_output_args(self):
        args: List[str] = ["g++", "foo.cpp", "-O0"]
        assert Arguments(args).remove_output_args() == args

        single_output_args: List[str] = args + ["-o", "foo"]
        assert Arguments(single_output_args).remove_output_args() == args

        multiple_output_args: List[str] = args + ["-o", "foo", "-o", "bar"]
        assert Arguments(multiple_output_args).remove_output_args() == args

        mixed_output_args: List[str] = args + ["-o", "foo", "-obar"]
        assert Arguments(mixed_output_args).remove_output_args() == args

        output_flag_as_output_target_args: List[str] = args + ["-ofoo", "-o", "-o"]
        assert Arguments(output_flag_as_output_target_args).remove_output_args() == args

        # ignore ill-formed output arguments
        ill_formed_output_args: List[str] = args + ["-ofoo", "-o"]
        assert Arguments(ill_formed_output_args).remove_output_args() == args

    def test_single_source_file_args(self):
        source_file_arg: List[str] = ["some/relative/path.c"]
        args: List[str] = ["g++", "-O3"] + source_file_arg

        assert Arguments(args).source_files == source_file_arg

    def test_multiple_source_file_args_with_output(self):
        source_file_args: List[str] = [
            "main.cpp",
            "relative/relative.cpp",
            "/opt/src/absolute.cpp",
        ]
        args: List[str] = [
            "g++",
            "-Irelative_path/relative.h",
            "-I",
            "/var/includes/absolute.h",
            "-o",
            "out",
        ] + source_file_args

        assert Arguments(args).source_files == source_file_args

    def test_replace_source_with_object_files(self):
        source_file_to_object_file: Dict[str, str] = {
            "main.cpp": "main.o",
            "relative/relative.cpp": "relative/relative.o",
            "/opt/src/absolute.cpp": "/opt/src/absolute.o",
        }
        args: List[str] = [
            "g++",
            "-Irelative_path/relative.h",
            "-I",
            "/var/includes/absolute.h",
        ]

        arguments: Arguments = Arguments(args + list(source_file_to_object_file.keys()))
        arguments.replace_source_files_with_object_files(source_file_to_object_file)

        assert arguments == args + list(source_file_to_object_file.values())
