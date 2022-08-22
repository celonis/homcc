"""Tests regarding the arguments module of homcc."""
from typing import List, Optional

import pytest

from homcc.common.arguments import Arguments, Clang, Compiler, Gcc
from homcc.common.errors import UnsupportedCompilerError


class TestArguments:
    """Tests for common/arguments.py"""

    def test_arguments(self):
        args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        arguments: Arguments = Arguments.from_args(args)
        assert arguments != Arguments.from_args(args + ["-ofoo"])
        assert str(arguments) == "[g++ foo.cpp -O0 -Iexample/include/]"
        assert repr(arguments) == f"{Arguments}([g++ foo.cpp -O0 -Iexample/include/])"
        arguments.compiler = "clang++"
        assert arguments.compiler == "clang++"

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

    def test_from_args(self):
        with pytest.raises(ValueError):
            Arguments.from_args([])

        compiler_args: List[str] = ["g++"]
        assert Arguments.from_args(compiler_args) == compiler_args

        args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        assert Arguments.from_args(args) == args

    def test_from_cli(self):
        specified_compiler_cli_args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        arguments = Arguments.from_cli(specified_compiler_cli_args[0], specified_compiler_cli_args[1:], "gcc")
        assert arguments == specified_compiler_cli_args

        unspecified_compiler_cli_args: List[str] = specified_compiler_cli_args[1:]
        arguments = Arguments.from_cli(unspecified_compiler_cli_args[0], unspecified_compiler_cli_args[1:], "gcc")
        assert arguments == Arguments("gcc", unspecified_compiler_cli_args)

    def test_is_sendable(self):
        args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        assert Arguments.from_args(args).is_sendable()

        sendable_args: List[str] = args + ["-c", "-ofoo"]
        assert Arguments.from_args(sendable_args).is_sendable()

        sendable_preprocessor_args: List[str] = args + ["-MD", "-MF", "foo.d"]
        assert Arguments.from_args(sendable_preprocessor_args).is_sendable()

        # unsendability
        no_source_files_args: List[str] = args[1:]
        assert not Arguments.from_args(no_source_files_args).is_sendable()

        ambiguous_output_args: List[str] = args + ["-o", "-"]
        assert not Arguments.from_args(ambiguous_output_args).is_sendable()

        unknown_language_args: List[str] = args + ["-x", "unsendable"]
        assert not Arguments.from_args(unknown_language_args).is_sendable()

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
            assert not Arguments.from_args(args + [unsendable_arg]).is_sendable()

    def test_is_linking(self):
        linking_args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/", "-ofoo"]
        assert Arguments.from_args(linking_args).is_linking()

        not_linking_args: List[str] = linking_args + ["-c"]
        assert not Arguments.from_args(not_linking_args).is_linking()

    def test_is_linking_only(self):
        compile_and_link_args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        assert not Arguments.from_args(compile_and_link_args).is_linking_only()

        compile_and_no_link_args: List[str] = compile_and_link_args + ["-c"]
        assert not Arguments.from_args(compile_and_no_link_args).is_linking_only()

        linking_only_args: List[str] = ["g++", "foo.o", "bar.o", "-ofoobar"]
        assert Arguments.from_args(linking_only_args).is_linking_only()

    def test_dependency_finding_filename(self):
        source_file_args_str: str = "g++ -Iexample/include -c example/src/main.cpp"
        assert Arguments.from_str(source_file_args_str).dependency_finding()[1] is None

        simple_dependency_args_str: str = f"{source_file_args_str} -MD"
        assert Arguments.from_str(simple_dependency_args_str).dependency_finding()[1] == "main.d"

        dependency_target_args_str: str = f"{simple_dependency_args_str} -MT main.cpp.o"
        assert Arguments.from_str(dependency_target_args_str).dependency_finding()[1] == "main.d"

        dependency_file_args_str: str = f"{dependency_target_args_str} -MF main.cpp.o.d"
        assert Arguments.from_str(dependency_file_args_str).dependency_finding()[1] == "main.cpp.o.d"

        duplicated_dependency_file_args_str: str = f"{dependency_target_args_str} -MF main.cpp.o.d -MF foo.cpp.o.d"
        assert Arguments.from_str(duplicated_dependency_file_args_str).dependency_finding()[1] == "foo.cpp.o.d"

        output_dependency_file_args_str: str = f"{dependency_target_args_str} -o main.cpp.o"
        assert Arguments.from_str(output_dependency_file_args_str).dependency_finding()[1] == "main.cpp.d"

        multiple_dependency_file_args_str: str = f"{dependency_target_args_str} -MF main.cpp.o.d -o main.cpp.o"
        assert Arguments.from_str(multiple_dependency_file_args_str).dependency_finding()[1] == "main.cpp.o.d"

    def test_output_target(self):
        args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
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
        with pytest.raises(StopIteration):
            ill_formed_output_args: List[str] = args + ["-ofoo", "-o"]
            _: Optional[str] = Arguments.from_args(ill_formed_output_args).output

    def test_remove_local_args(self):
        args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        assert Arguments.from_args(args).remove_local_args() == args

        local_args: List[str] = (
            Arguments.Local.LINKER_OPTION_PREFIX_ARGS + Arguments.Local.PREPROCESSOR_OPTION_PREFIX_ARGS
        )

        for preprocessing_arg in Arguments.Local.PREPROCESSOR_ARGS:
            assert Arguments.from_args(args + [preprocessing_arg]).remove_local_args() == args

        local_option_args: List[str] = args.copy()
        for local_option_arg in local_args:
            local_option_args.extend([local_option_arg, "option"])
        assert Arguments.from_args(local_option_args).remove_local_args() == args

        local_prefixed_args: List[str] = args + [f"{arg_prefix}suffix" for arg_prefix in local_args]
        assert Arguments.from_args(local_prefixed_args).remove_local_args() == args

    def test_remove_output_args(self):
        args: List[str] = ["g++", "foo.cpp", "-O0", "-Iexample/include/"]
        assert Arguments.from_args(args).remove_output_args() == args

        single_output_args: List[str] = args + ["-o", "foo"]
        assert Arguments.from_args(single_output_args).remove_output_args() == args

        multiple_output_args: List[str] = args + ["-o", "foo", "-o", "bar"]
        assert Arguments.from_args(multiple_output_args).remove_output_args() == args

        mixed_output_args: List[str] = args + ["-o", "foo", "-obar"]
        assert Arguments.from_args(mixed_output_args).remove_output_args() == args

        output_flag_as_output_target_args: List[str] = args + ["-ofoo", "-o", "-o"]
        assert Arguments.from_args(output_flag_as_output_target_args).remove_output_args() == args

        # failing output removal as 2nd output argument has no specified target
        with pytest.raises(StopIteration):
            ill_formed_output_args: List[str] = args + ["-ofoo", "-o"]
            _: Arguments = Arguments.from_args(ill_formed_output_args).remove_output_args()

        # test cached_property of output
        single_output_remove_args: List[str] = args + ["-o", "foo"]
        single_output_remove_arguments: Arguments = Arguments.from_args(single_output_remove_args)
        assert single_output_remove_arguments.output == "foo"
        assert single_output_remove_arguments.add_arg("-obar").output == "foo"  # no change as property is cached
        assert single_output_remove_arguments.remove_output_args().output is None
        assert single_output_remove_arguments.add_arg("-obar").output is None  # no change as property is cached

        multiple_output_remove_args: List[str] = args + ["-o", "foo", "-o", "bar"]
        multiple_output_remove_arguments: Arguments = Arguments.from_args(multiple_output_remove_args)
        assert multiple_output_remove_arguments.output == "bar"
        assert multiple_output_remove_arguments.add_arg("-obaz").output == "bar"  # no change as property is cached
        assert multiple_output_remove_arguments.remove_output_args().output is None
        assert multiple_output_remove_arguments.add_arg("-obaz").output is None  # no change as property is cached

    def test_remove_source_file_args(self):
        args: List[str] = ["g++", "-O0", "-Iexample/include/"]
        source_files: List[str] = ["foo.cpp", "bar.cpp"]

        source_file_args: List[str] = args + source_files
        source_file_arguments: Arguments = Arguments.from_args(source_file_args)
        assert source_file_arguments.source_files == source_files
        assert source_file_arguments.add_arg("baz.cpp").source_files == source_files  # no change as property is cached
        assert not source_file_arguments.remove_source_file_args().source_files
        assert not source_file_arguments.add_arg("baz.cpp").source_files  # no change as property is cached

    def test_single_source_file_args(self):
        single_source_file_args: List[str] = ["some/relative/path.c"]
        assert Arguments.from_args(["g++"] + single_source_file_args).source_files == single_source_file_args
        assert Arguments.from_args(["g++", "-O3"] + single_source_file_args).source_files == single_source_file_args

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

    def test_compiler_normalized(self):
        assert Arguments.from_args(["gcc", "foo"]).compiler_normalized() == "gcc"
        assert Arguments.from_args(["/usr/bin/gcc", "foo"]).compiler_normalized() == "gcc"
        assert Arguments.from_args(["~/bin/g++", "foo"]).compiler_normalized() == "g++"
        assert Arguments.from_args(["../custom_compiler.py", "foo"]).compiler_normalized() == "custom_compiler.py"


class TestCompiler:
    """Tests the compiler class of homcc."""

    def test_from_arguments(self):
        assert isinstance(Compiler.from_arguments(Arguments("gcc", [])), Gcc)
        assert isinstance(Compiler.from_arguments(Arguments("gcc-11", [])), Gcc)
        assert isinstance(Compiler.from_arguments(Arguments("g++", [])), Gcc)
        assert isinstance(Compiler.from_arguments(Arguments("g++-11", [])), Gcc)
        assert isinstance(Compiler.from_arguments(Arguments("/usr/lib/ccache/gcc-11", [])), Gcc)

        assert isinstance(Compiler.from_arguments(Arguments("clang++", [])), Clang)
        assert isinstance(Compiler.from_arguments(Arguments("clang++-11", [])), Clang)
        assert isinstance(Compiler.from_arguments(Arguments("/usr/lib/ccache/clang-14", [])), Clang)

        with pytest.raises(UnsupportedCompilerError):
            Compiler.from_arguments(Arguments("unknown++", []))


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

        arguments = Arguments.from_args(["g++", "-Iexample/include", "example/src/*"])
        new_arguments = gcc.add_target_to_arguments(arguments, "x86_64")
        assert new_arguments.compiler == "x86_64-g++"

        arguments = Arguments.from_args(["x86_64-g++-11", "-Iexample/include", "example/src/*"])
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

        arguments = Arguments.from_args(["clang++", "-Iexample/include", "example/src/*"])
        new_arguments = clang.add_target_to_arguments(arguments, "x86_64")
        assert "--target=x86_64" in new_arguments.args

        arguments = Arguments.from_args(["clang++", "-Iexample/include", "example/src/*", "--target=aarch64"])
        new_arguments = clang.add_target_to_arguments(arguments, "x86_64")
        assert "--target=aarch64" in new_arguments.args
        assert "--target=x86_64" not in new_arguments.args

        arguments = Arguments.from_args(["clang++", "-Iexample/include", "example/src/*", "-target", "aarch64"])
        new_arguments = clang.add_target_to_arguments(arguments, "x86_64")
        assert "aarch64" in new_arguments.args
        assert "--target=x86_64" not in new_arguments.args
