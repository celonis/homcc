# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Tests regarding the arguments module of homcc."""
from pathlib import Path
from typing import List, Optional

import pytest

from homcc.common.arguments import Arguments, Clang, Compiler, Gcc
from homcc.common.errors import UnsupportedCompilerError


class TestArguments:
    """Tests for common/arguments.py"""

    def test_arguments(self):
        args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        arguments: Arguments = Arguments.from_vargs(*args)
        assert arguments == args
        assert arguments == arguments.copy()
        assert arguments != Arguments.from_vargs(*args, "-ofoo")
        assert str(arguments) == "[g++ foo.cpp -O0 -Iexample/include/]"
        assert repr(arguments) == f"{Arguments}([g++ foo.cpp -O0 -Iexample/include/])"

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

    @pytest.mark.gplusplus
    def test_is_compiler_arg(self):
        assert Arguments.is_compiler_arg("g++")

    def test_from_vargs(self):
        with pytest.raises(ValueError):
            Arguments.from_vargs()

        assert Arguments.from_vargs("g++") == ["g++"]

        args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        assert Arguments.from_vargs(*args) == args

    def test_is_sendable(self):
        args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        assert Arguments.from_vargs(*args).is_sendable()
        assert Arguments.from_vargs(*args, "-c", "-ofoo").is_sendable()
        assert Arguments.from_vargs(*args, "-MD", "-MF", "foo.d").is_sendable()  # sendable preprocessor

        # unsendability
        assert not Arguments.from_vargs(args[0], *args[2:]).is_sendable()  # no source files
        assert not Arguments.from_vargs(*args, "-o", "-").is_sendable()  # ambiguous output
        assert not Arguments.from_vargs(*args, "-x", "unsendable").is_sendable()  # unknown language

        unsendable_args: List[str] = [
            "-E",
            "-MM",
            "-march=native",
            "-mtune=native",
            "-S",
            "-Wa,-a",
            "-specs=Unsendable",
            "-fprofile-generate=Unsendable",
            "-frepo",
            "-drUnsendable",
        ]
        for unsendable_arg in unsendable_args:
            assert not Arguments.from_vargs(*args, unsendable_arg).is_sendable()

    def test_is_linking(self):
        linking_args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/", "-ofoo"]
        assert Arguments.from_vargs(*linking_args).is_linking()
        assert not Arguments.from_vargs(*linking_args, "-c").is_linking()

    def test_is_linking_only(self):
        compile_and_link_args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        assert not Arguments.from_vargs(*compile_and_link_args).is_linking_only()  # compile and link
        assert not Arguments.from_vargs(*compile_and_link_args, "-c").is_linking_only()  # compile and no link

        assert Arguments.from_vargs("g++", "foo.o", "bar.o", "-ofoobar").is_linking_only()  # linking only

    def test_dependency_finding_filename(self):
        source_file_args: List[str] = [
            "g++",
            "-Iexample/include",
            "-c",
            "example/src/main.cpp",
        ]
        assert Arguments.from_vargs(*source_file_args).dependency_finding()[1] is None

        simple_dependency_args: List[str] = source_file_args + ["-MD"]
        assert Arguments.from_vargs(*simple_dependency_args).dependency_finding()[1] == "main.d"

        dependency_target_args: List[str] = simple_dependency_args + ["-MT", "main.cpp.o"]
        assert Arguments.from_vargs(*dependency_target_args).dependency_finding()[1] == "main.d"

        assert (  # dependency_file_args
            Arguments.from_vargs(*dependency_target_args, "-MF", "main.cpp.o.d").dependency_finding()[1]
            == "main.cpp.o.d"
        )

        assert (  # duplicated_dependency_file_args
            Arguments.from_vargs(
                *dependency_target_args, "-MF", "main.cpp.o.d", "-MF", "foo.cpp.o.d"
            ).dependency_finding()[1]
            == "foo.cpp.o.d"
        )

        # output_dependency_file_args
        assert Arguments.from_vargs(*dependency_target_args, "-o", "main.cpp.o").dependency_finding()[1] == "main.cpp.d"

        assert (  # multiple_dependency_file_args
            Arguments.from_vargs(
                *dependency_target_args, "-MF", "main.cpp.o.d", "-o", "main.cpp.o"
            ).dependency_finding()[1]
            == "main.cpp.o.d"
        )

    def test_output_target(self):
        args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        assert Arguments.from_vargs(*args).output is None

        assert Arguments.from_vargs(*args, "-o", "foo").output == "foo"  # single output
        assert Arguments.from_vargs(*args, "-o", "foo", "-o", "bar").output == "bar"  # multiple output
        assert Arguments.from_vargs(*args, "-o", "foo", "-obar").output == "bar"  # mixed output
        assert Arguments.from_vargs(*args, "-ofoo", "-o", "-o").output == "-o"  # output flag as output
        assert Arguments.from_vargs(*args, "-o", "long/path/to/output").output == "long/path/to/output"  # output path

        # failing output extraction as 2nd output argument has no specified target
        with pytest.raises(StopIteration):
            _: Optional[str] = Arguments.from_vargs(*args, "-ofoo", "-o").output

    def test_remove_local_args(self):
        args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        assert Arguments.from_vargs(*args).remove_local_args() == args

        local_args: List[str] = (
            Arguments.Local.LINKER_OPTION_PREFIX_ARGS + Arguments.Local.PREPROCESSOR_OPTION_PREFIX_ARGS
        )

        for preprocessing_arg in Arguments.Local.PREPROCESSOR_ARGS:
            assert Arguments.from_vargs(*args, preprocessing_arg).remove_local_args() == args

        local_option_args: List[str] = args.copy()
        for local_option_arg in local_args:
            local_option_args.extend([local_option_arg, "option"])
        assert Arguments.from_vargs(*local_option_args).remove_local_args() == args

        local_prefixed_args: List[str] = args + [f"{arg_prefix}suffix" for arg_prefix in local_args]
        assert Arguments.from_vargs(*local_prefixed_args).remove_local_args() == args

    def test_remove_output_args(self):
        args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        assert Arguments.from_vargs(*args).remove_output_args() == args  # no output
        assert Arguments.from_vargs(*args, "-o", "foo").remove_output_args() == args  # single output
        assert Arguments.from_vargs(*args, "-o", "foo", "-o", "bar").remove_output_args() == args  # multiple outputs
        assert Arguments.from_vargs(*args, "-o", "foo", "-obar").remove_output_args() == args  # mixed outputs
        assert Arguments.from_vargs(*args, "-ofoo", "-o", "-o").remove_output_args() == args  # output flag target

        # failing output removal as 2nd output argument has no specified target
        with pytest.raises(StopIteration):
            _: Arguments = Arguments.from_vargs(*args, "-ofoo", "-o").remove_output_args()

        # test cached_property of output
        single_output_remove_arguments: Arguments = Arguments.from_vargs(*args, "-o", "foo")
        assert single_output_remove_arguments.output == "foo"
        assert single_output_remove_arguments.add_arg("-obar").output == "foo"  # no change as property is cached
        assert single_output_remove_arguments.remove_output_args().output is None
        assert single_output_remove_arguments.add_arg("-obar").output is None  # no change as property is cached

        multiple_output_remove_arguments: Arguments = Arguments.from_vargs(*args, "-o", "foo", "-o", "bar")
        assert multiple_output_remove_arguments.output == "bar"
        assert multiple_output_remove_arguments.add_arg("-obaz").output == "bar"  # no change as property is cached
        assert multiple_output_remove_arguments.remove_output_args().output is None
        assert multiple_output_remove_arguments.add_arg("-obaz").output is None  # no change as property is cached

    def test_remove_source_file_args(self):
        args: List[str] = ["g++", "-O0", "-Iexample/include/"]
        source_files: List[str] = ["foo.cpp", "bar.cpp"]

        source_file_arguments: Arguments = Arguments.from_vargs(*args, *source_files)
        assert source_file_arguments.source_files == source_files
        assert source_file_arguments.add_arg("baz.cpp").source_files == source_files  # no change as property is cached
        assert not source_file_arguments.remove_source_file_args().source_files
        assert not source_file_arguments.add_arg("baz.cpp").source_files  # no change as property is cached

    def test_single_source_file_args(self):
        single_source_file_args: List[str] = ["some/relative/path.c"]
        assert Arguments.from_vargs("g++", *single_source_file_args).source_files == single_source_file_args
        assert Arguments.from_vargs("g++", "-O3", *single_source_file_args).source_files == single_source_file_args

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

        assert Arguments.from_vargs(*args).source_files == source_file_args

    def test_compiler_normalization(self):
        assert Arguments.from_vargs("gcc", "foo").normalize_compiler().compiler == "gcc"
        assert Arguments.from_vargs("/usr/bin/gcc", "foo").normalize_compiler().compiler == "gcc"
        assert Arguments.from_vargs("~/bin/g++", "foo").normalize_compiler().compiler == "g++"

    def test_relativize_output(self):
        assert (
            Arguments.from_vargs("gcc", "-o", "/home/user/abc.o").relativize_output(Path("/home/user")).output
            == "abc.o"
        )
        assert (
            Arguments.from_vargs("gcc", "-o", "/home/user/./../user/abc.o").relativize_output(Path("/home/user")).output
            == "../user/abc.o"
        )
        assert (
            Arguments.from_vargs("gcc", "-o", "/home/user/abc.o").relativize_output(Path("/home/")).output
            == "user/abc.o"
        )

    def test_add_output(self):
        assert Arguments.from_vargs("gcc").add_output("foo.o").output == "foo.o"
        assert Arguments.from_vargs("gcc", "-oabc.o").add_output("foo.o").output == "foo.o"


class TestCompiler:
    """Tests the compiler class of homcc."""

    def test_from_arguments(self):
        assert isinstance(Compiler.from_str("gcc"), Gcc)
        assert isinstance(Compiler.from_str("gcc-11"), Gcc)
        assert isinstance(Compiler.from_str("g++"), Gcc)
        assert isinstance(Compiler.from_str("g++-11"), Gcc)
        assert isinstance(Compiler.from_str("/usr/lib/ccache/gcc-11"), Gcc)

        assert isinstance(Compiler.from_str("clang++"), Clang)
        assert isinstance(Compiler.from_str("clang++-11"), Clang)
        assert isinstance(Compiler.from_str("/usr/lib/ccache/clang-14"), Clang)

        with pytest.raises(UnsupportedCompilerError):
            Compiler.from_str("unknown++")


class TestGcc:
    """Tests the Gcc class."""

    @pytest.mark.gplusplus
    def test_supports_target(self):
        gcc = Gcc("g++")
        assert gcc.supports_target("x86_64-linux-gnu")
        assert not gcc.supports_target("other_arch-linux-gnu")

    @pytest.mark.gplusplus
    def test_get_target_triple(self):
        gcc = Gcc("g++")
        assert gcc.get_target_triple()  # check no exception is thrown and we got a non-empty string

    def test_add_target_to_arguments(self):
        gcc = Gcc("g++")

        arguments = Arguments.from_vargs("g++", "-Iexample/include", "example/src/*")
        new_arguments = gcc.add_target_to_arguments(arguments, "x86_64")
        assert new_arguments.compiler == "x86_64-g++"

        arguments = Arguments.from_vargs("x86_64-g++-11", "-Iexample/include", "example/src/*")
        new_arguments = gcc.add_target_to_arguments(arguments, "x86_64")
        assert new_arguments.compiler == "x86_64-g++-11"  # do not substitute if already substituted


class TestClang:
    """Tests the Clang class."""

    @pytest.mark.clangplusplus
    def test_get_target_triple(self):
        clang = Clang("clang++")
        assert clang.get_target_triple()  # check no exception is thrown and we got a non-empty string

    def test_add_target_to_arguments(self):
        clang = Clang("clang++")

        arguments = Arguments.from_vargs("clang++", "-Iexample/include", "example/src/*")
        new_arguments = clang.add_target_to_arguments(arguments, "x86_64")
        assert "--target=x86_64" in new_arguments.args

        arguments = Arguments.from_vargs("clang++", "-Iexample/include", "example/src/*", "--target=aarch64")
        new_arguments = clang.add_target_to_arguments(arguments, "x86_64")
        assert "--target=aarch64" in new_arguments.args
        assert "--target=x86_64" not in new_arguments.args

        arguments = Arguments.from_vargs("clang++", "-Iexample/include", "example/src/*", "-target", "aarch64")
        new_arguments = clang.add_target_to_arguments(arguments, "x86_64")
        assert "aarch64" in new_arguments.args
        assert "--target=x86_64" not in new_arguments.args
