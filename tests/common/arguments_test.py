"""Tests regarding the arguments module of homcc."""
import pytest
import shutil

from typing import Dict, List, Optional, Union
from homcc.common.arguments import Arguments, ArgumentsOutputError


class TestArguments:
    """Tests for common/arguments.py"""

    compiler_candidates: List[str] = ["cc", "gcc", "g++", "clang", "clang++"]
    compilers: List[str] = list(filter(lambda compiler: shutil.which(compiler) is not None, compiler_candidates))

    def test_is_source_file_arg(self):
        source_files: List[str] = ["foo.c", "bar.cpp"]
        for source_file in source_files:
            assert Arguments.is_source_file_arg(source_file)

        not_source_files: List[str] = ["", ".", ".cpp", "foo.hpp"]
        for not_source_file in not_source_files:
            assert not Arguments.is_source_file_arg(not_source_file)

    def test_is_object_file_arg(self):
        object_file: str = "foo.o"
        assert Arguments.is_object_file_arg(object_file)

        not_object_files: List[str] = ["", ".", ".o"]
        for not_object_file in not_object_files:
            assert not Arguments.is_object_file_arg(not_object_file)

    @pytest.mark.skipif(len(compilers) == 0, reason=f"No compiler of {compiler_candidates} installed to test")
    def test_is_compiler_arg(self):
        for compiler in self.compilers:
            assert Arguments.is_compiler_arg(compiler)

    def test_from_args(self):
        with pytest.raises(ValueError):
            Arguments.from_args([])

        compiler_args: List[str] = ["g++"]
        assert Arguments.from_args(compiler_args) == compiler_args

        args: List[str] = ["g++", "-c", "foo.cpp"]
        assert Arguments.from_args(args) == args

    def test_from_cli(self):
        specified_compiler_cli_args: List[str] = ["g++", "-c", "foo.cpp"]
        arguments = Arguments.from_cli(specified_compiler_cli_args[0], specified_compiler_cli_args[1:])
        assert arguments == specified_compiler_cli_args

        unspecified_compiler_cli_args: List[str] = specified_compiler_cli_args[1:]
        arguments = Arguments.from_cli(unspecified_compiler_cli_args[0], unspecified_compiler_cli_args[1:])
        assert arguments == Arguments(None, unspecified_compiler_cli_args)

    def test_is_sendable(self):
        args: List[str] = ["g++", "foo.cpp"]
        assert Arguments.from_args(args).is_sendable()

        sendable_args: List[str] = args + ["-c", "-ofoo"]
        assert Arguments.from_args(sendable_args).is_sendable()

        # unsendability
        unsendable_args_dict: Dict[str, Union[str, List[str]]] = {
            # extract all relevant argument fields from Argument.Unsendable
            k: v
            for k, v in vars(Arguments.Unsendable).items()
            if not (k.startswith("__") and k.endswith("__"))
        }

        # unsendable prefix args: naming ends on "_prefix"
        unsendable_prefix_args: List[str] = [v for k, v in unsendable_args_dict.items() if k.endswith("_prefix")]

        for prefix_arg in unsendable_prefix_args:
            unsendable_args: List[str] = args + [f"{prefix_arg}dummy_suffix"]
            assert not Arguments.from_args(unsendable_args).is_sendable()

        # unsendable single args: naming ends on "_arg"
        unsendable_single_args: List[str] = [v for k, v in unsendable_args_dict.items() if k.endswith("_arg")]

        for single_arg in unsendable_single_args:
            unsendable_args: List[str] = args + [single_arg]
            assert not Arguments.from_args(unsendable_args).is_sendable()

        # unsendable arg families: naming ends on "_args"
        unsendable_arg_families: List[List[str]] = [v for k, v in unsendable_args_dict.items() if k.endswith("_args")]

        for arg_family in unsendable_arg_families:
            for arg in arg_family:
                unsendable_args: List[str] = args + [arg]
                assert not Arguments.from_args(unsendable_args).is_sendable()

    def test_is_linking(self):
        linking_args: List[str] = ["g++", "foo.cpp", "-ofoo"]
        assert Arguments.from_args(linking_args).is_linking()

        not_linking_args: List[str] = ["g++", "foo.cpp", "-c"]
        assert not Arguments.from_args(not_linking_args).is_linking()

    def test_output_target(self):
        args: List[str] = ["g++", "foo.cpp", "-O0"]
        assert Arguments.from_args(args).output is None

        single_output_args: List[str] = args + ["-o", "foo"]
        assert Arguments.from_args(single_output_args).output == "foo"

        multiple_output_args: List[str] = args + ["-o", "foo", "-o", "bar"]
        assert Arguments.from_args(multiple_output_args).output == "bar"

        mixed_output_args: List[str] = args + ["-o", "foo", "-obar"]
        assert Arguments.from_args(mixed_output_args).output == "bar"

        output_flag_as_output_args: List[str] = args + ["-ofoo", "-o", "-o"]
        assert Arguments.from_args(output_flag_as_output_args).output == "-o"

        long_output_path_args: List[str] = args + ["-o", "long/path/to/output"]
        assert Arguments.from_args(long_output_path_args).output == "long/path/to/output"

        # failing output extraction as 2nd output argument has no specified target
        with pytest.raises(ArgumentsOutputError):
            ill_formed_output_args: List[str] = args + ["-ofoo", "-o"]
            _: Optional[str] = Arguments.from_args(ill_formed_output_args).output

    def test_add_output_arg(self):
        output: str = "foo"

        args: List[str] = ["g++", "foo.cpp", "-O0"]
        arguments: Arguments = Arguments.from_args(args)
        arguments.output = output
        assert arguments.output == output

        multiple_output_args: List[str] = args + ["-o", "foo", "-o", "bar"]
        multiple_output_arguments: Arguments = Arguments.from_args(multiple_output_args)
        assert multiple_output_arguments.output == "bar"
        multiple_output_arguments.output = output
        assert multiple_output_arguments.output == output

    def test_remove_local_args(self):
        args: List[str] = ["g++", "foo.cpp", "-O0"]
        assert Arguments.from_args(args).remove_local_args() == args

        local_option_args: List[str] = args.copy()
        for local_option_arg in Arguments.Local.option_args:
            local_option_args.extend([local_option_arg, "option"])
        assert Arguments.from_args(local_option_args).remove_local_args() == args

        local_prefixed_args: List[str] = args + [f"{arg_prefix}suffix" for arg_prefix in Arguments.Local.arg_prefixes]
        assert Arguments.from_args(local_prefixed_args).remove_local_args() == args

        local_cpp_args: List[str] = args + Arguments.Local.cpp_args
        assert Arguments.from_args(local_cpp_args).remove_local_args() == args

    def test_remove_output_args(self):
        args: List[str] = ["g++", "foo.cpp", "-O0"]
        assert Arguments.from_args(args).remove_output_args() == args

        single_output_args: List[str] = args + ["-o", "foo"]
        assert Arguments.from_args(single_output_args).remove_output_args() == args

        multiple_output_args: List[str] = args + ["-o", "foo", "-o", "bar"]
        assert Arguments.from_args(multiple_output_args).remove_output_args() == args

        mixed_output_args: List[str] = args + ["-o", "foo", "-obar"]
        assert Arguments.from_args(mixed_output_args).remove_output_args() == args

        output_flag_as_output_target_args: List[str] = args + ["-ofoo", "-o", "-o"]
        assert Arguments.from_args(output_flag_as_output_target_args).remove_output_args() == args

        # ignore ill-formed output arguments
        ill_formed_output_args: List[str] = args + ["-ofoo", "-o"]
        assert Arguments.from_args(ill_formed_output_args).remove_output_args() == args

    def test_single_source_file_args(self):
        source_file_arg: List[str] = ["some/relative/path.c"]
        args: List[str] = ["g++", "-O3"] + source_file_arg

        assert Arguments.from_args(args).source_files == source_file_arg

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

        assert Arguments.from_args(args).source_files == source_file_args
