"""Tests regarding the arguments module of homcc."""
import pytest

from typing import List, Optional
from homcc.common.arguments import Arguments, ArgumentsOutputError


class TestArguments:
    """Tests for common/arguments.py"""

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
