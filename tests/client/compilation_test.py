# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Tests for client/compilation.py"""
import asyncio
import logging
import os
import subprocess
from contextlib import nullcontext
from pathlib import Path
from typing import List, Set

import pytest

from homcc.client import compilation
from homcc.client.compilation import (
    _compiler_is_homcc,
    _log_dependency_discrepancy,
    compile_locally,
    compile_remotely_at,
    find_dependencies,
    scan_includes,
)
from homcc.client.config import ClientConfig
from homcc.client.parsing import Host
from homcc.client.preprocessing_cache import DependencyAnalysis
from homcc.common.arguments import Arguments
from homcc.common.compression import NoCompression
from homcc.common.constants import ENCODING
from homcc.common.errors import RemoteCompilationError
from homcc.common.messages import CompilationResultMessage


class TestCompilation:
    """Tests for functions in client/compilation.py"""

    @staticmethod
    def _remote_result_client(result: CompilationResultMessage):
        class ResultClient:
            """Minimal asynchronous client returning one compilation result."""

            connection_target = "remote:3126"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def send_argument_message(self, **_):
                return None

            async def receive(self):
                return result

        return ResultClient()

    @staticmethod
    def _compilation_state():
        class CompilationState:
            """Minimal state-file replacement for direct remote compilation tests."""

            @staticmethod
            def set_compile():
                return None

        return CompilationState()

    def test_failed_remote_compilation_does_not_trigger_legacy_server_fallback(self, monkeypatch: pytest.MonkeyPatch):
        arguments = Arguments.from_vargs("g++", "-MD", "-MF", "main.d", "-c", "main.cpp")
        response = CompilationResultMessage([], "", "missing dependency", os.EX_DATAERR, NoCompression(), [])
        fallback_calls = []
        recorded_stats = []

        monkeypatch.setattr(
            compilation,
            "create_remote_client",
            lambda *_: self._remote_result_client(response),
        )
        monkeypatch.setattr(Arguments, "get_compiler_target_triple", lambda *_, **__: None)
        monkeypatch.setattr(compilation, "find_dependencies", lambda *_: fallback_calls.append(True))
        monkeypatch.setattr(compilation, "record_cache_stat", lambda name, *_: recorded_stats.append(name))

        with pytest.raises(RemoteCompilationError):
            asyncio.run(
                compile_remotely_at(
                    arguments,
                    {},
                    Host.from_str("remote/1"),
                    ClientConfig.empty(),
                    self._compilation_state(),
                )
            )

        assert not fallback_calls
        assert "legacy_server_fallbacks" not in recorded_stats

    def test_successful_response_without_dependency_file_triggers_legacy_server_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        arguments = Arguments.from_vargs("g++", "-MD", "-MF", "main.d", "-c", "main.cpp")
        response = CompilationResultMessage([], "", "", os.EX_OK, NoCompression(), [])
        fallback_calls = []
        recorded_stats = []

        monkeypatch.setattr(
            compilation,
            "create_remote_client",
            lambda *_: self._remote_result_client(response),
        )
        monkeypatch.setattr(Arguments, "get_compiler_target_triple", lambda *_, **__: None)
        monkeypatch.setattr(compilation, "find_dependencies", lambda *_: fallback_calls.append(True))
        monkeypatch.setattr(compilation, "record_cache_stat", lambda name, *_: recorded_stats.append(name))

        result = asyncio.run(
            compile_remotely_at(
                arguments,
                {},
                Host.from_str("remote/1"),
                ClientConfig.empty(),
                self._compilation_state(),
            )
        )

        assert result == os.EX_OK
        assert fallback_calls == [True]
        assert recorded_stats == ["legacy_server_fallbacks"]

    def test_scan_includes(self):
        arguments: Arguments = Arguments.from_vargs(
            "g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp"
        )

        includes: List[str] = scan_includes(arguments)

        assert len(includes) == 1
        assert str(Path("example/include/foo.h").absolute()) in includes

    def test_detects_homcc_compiler_symlink(self, tmp_path: Path):
        compiler = tmp_path / "clang-homcc"
        compiler.symlink_to(Path("homcc/client/main.py").absolute())

        assert _compiler_is_homcc(Arguments.from_vargs(str(compiler), "main.cpp").compiler)

    def test_logs_missing_dependencies_in_sorted_order(self, caplog: pytest.LogCaptureFixture):
        with caplog.at_level(logging.WARNING):
            _log_dependency_discrepancy({"/project/z.h", "/project/a.h"})

        assert caplog.messages == [
            "Cached include analysis missed #2 dependencies; retrying once with compiler results:\n"
            "  /project/a.h\n"
            "  /project/z.h"
        ]

    def test_learns_supplements_only_after_successful_exact_retry(self, monkeypatch: pytest.MonkeyPatch):
        arguments = Arguments.from_vargs("g++", "source.cpp", "-c")
        host = Host.from_str("remote/1")
        analysis = DependencyAnalysis(
            dependencies={"/project/source.cpp": "source-hash"},
            base_dependencies={"/project/source.cpp": "source-hash"},
            profile="profile",
        )
        exact_dependencies = {
            "/project/source.cpp": "source-hash",
            "/project/generated.hpp": "generated-hash",
        }
        config = ClientConfig.empty()
        attempts = []
        learned = []

        async def compile_with_retry(**kwargs):
            attempts.append(kwargs["dependency_dict"])
            if len(attempts) == 1:
                raise RemoteCompilationError("missing dependency", os.EX_DATAERR)
            return os.EX_OK

        monkeypatch.setattr(
            compilation, "_preprocess", lambda *_: compilation.PreprocessingResult(analysis.dependencies, analysis)
        )
        monkeypatch.setattr(compilation, "RemoteHostSelector", lambda *_: [host])
        monkeypatch.setattr(compilation, "RemoteHostSemaphore", lambda *_: nullcontext())
        monkeypatch.setattr(compilation, "StateFile", lambda *_: nullcontext())
        monkeypatch.setattr(compilation, "compile_remotely_at", compile_with_retry)
        monkeypatch.setattr(compilation, "find_dependencies", lambda *_: set(exact_dependencies))
        monkeypatch.setattr(compilation, "calculate_dependency_dict", lambda *_: exact_dependencies)
        monkeypatch.setattr(compilation, "record_cache_stat", lambda *_: None)
        monkeypatch.setattr(
            compilation,
            "learn_supplemental_dependencies",
            lambda *args: learned.append(args),
        )

        result = asyncio.run(compilation.compile_remotely(arguments, [host], Host.localhost_with_limit(1), config))

        assert result == os.EX_OK
        assert attempts == [analysis.dependencies, exact_dependencies]
        assert learned == [(analysis, exact_dependencies, config.max_preprocessing_cache_size_bytes)]

    def test_does_not_learn_when_exact_retry_fails(self, monkeypatch: pytest.MonkeyPatch):
        arguments = Arguments.from_vargs("g++", "source.cpp", "-c")
        host = Host.from_str("remote/1")
        analysis = DependencyAnalysis(
            dependencies={"/project/source.cpp": "source-hash"},
            base_dependencies={"/project/source.cpp": "source-hash"},
            profile="profile",
        )
        exact_dependencies = {
            "/project/source.cpp": "source-hash",
            "/project/generated.hpp": "generated-hash",
        }
        learned = []

        async def fail_compilation(**_):
            raise RemoteCompilationError("compilation failed", os.EX_DATAERR)

        monkeypatch.setattr(
            compilation, "_preprocess", lambda *_: compilation.PreprocessingResult(analysis.dependencies, analysis)
        )
        monkeypatch.setattr(compilation, "RemoteHostSelector", lambda *_: [host])
        monkeypatch.setattr(compilation, "RemoteHostSemaphore", lambda *_: nullcontext())
        monkeypatch.setattr(compilation, "StateFile", lambda *_: nullcontext())
        monkeypatch.setattr(compilation, "compile_remotely_at", fail_compilation)
        monkeypatch.setattr(compilation, "find_dependencies", lambda *_: set(exact_dependencies))
        monkeypatch.setattr(compilation, "calculate_dependency_dict", lambda *_: exact_dependencies)
        monkeypatch.setattr(compilation, "record_cache_stat", lambda *_: None)
        monkeypatch.setattr(compilation, "learn_supplemental_dependencies", lambda *args: learned.append(args))

        with pytest.raises(RemoteCompilationError):
            asyncio.run(
                compilation.compile_remotely(arguments, [host], Host.localhost_with_limit(1), ClientConfig.empty())
            )

        assert not learned

    @staticmethod
    def find_dependencies(compiler: str):
        args: List[str] = [compiler, "-Iexample/include", "example/src/main.cpp"]
        dependencies: Set[str] = find_dependencies(Arguments.from_vargs(*args))

        assert len(dependencies) == 2
        assert str(Path("example/src/main.cpp").absolute()) in dependencies
        assert str(Path("example/include/foo.h").absolute()) in dependencies

    @pytest.mark.gplusplus
    def test_find_dependencies_gplusplus(self):
        self.find_dependencies("g++")

    @pytest.mark.clangplusplus
    def test_find_dependencies_clangplusplus(self):
        self.find_dependencies("clang++")

    @staticmethod
    def find_dependencies_with_side_effects(compiler: str, tmp_path: Path):
        args: List[str] = [
            compiler,
            "-Iexample/include",
            "-MD",
            "-MT",
            "example/src/main.cpp.o",
            "-MF",
            f"{tmp_path}/main.cpp.o.d",
            "-o",
            f"{tmp_path}/main.cpp.o",
            "-c",
            "example/src/main.cpp",
        ]
        dependencies: Set[str] = find_dependencies(Arguments.from_vargs(*args))

        assert len(dependencies) == 2
        assert str(Path("example/src/main.cpp").absolute()) in dependencies
        assert str(Path("example/include/foo.h").absolute()) in dependencies

        assert Path(f"{tmp_path}/main.cpp.o.d").exists()
        assert Path(f"{tmp_path}/main.cpp.o").exists()

    @pytest.mark.gplusplus
    def test_find_dependencies_with_side_effects_gplusplus(self, tmp_path: Path):
        self.find_dependencies_with_side_effects("g++", tmp_path)

    @pytest.mark.clangplusplus
    def test_find_dependencies_with_side_effects_clangplusplus(self, tmp_path: Path):
        self.find_dependencies_with_side_effects("clang++", tmp_path)

    @staticmethod
    def find_dependencies_class_impl_with_compiler(compiler: str):
        dependencies: Set[str] = find_dependencies(
            Arguments.from_vargs(compiler, "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp")
        )

        assert len(dependencies) == 3
        assert str(Path("example/src/main.cpp").absolute()) in dependencies
        assert str(Path("example/src/foo.cpp").absolute()) in dependencies
        assert str(Path("example/include/foo.h").absolute()) in dependencies

    @pytest.mark.gplusplus
    def find_dependencies_with_class_impl_gplusplus(self):
        self.find_dependencies_class_impl_with_compiler("g++")

    @pytest.mark.clangplusplus
    def find_dependencies_with_class_impl_clangplusplus(self):
        self.find_dependencies_class_impl_with_compiler("clang++")

    def test_find_dependencies_error(self):
        with pytest.raises(subprocess.CalledProcessError):
            _: Set[str] = find_dependencies(
                Arguments.from_vargs(
                    "g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp", "-OError"
                )
            )

    def test_local_compilation(self):
        output: str = "compilation_test"
        args: List[str] = ["g++", "-Iexample/include", "example/src/main.cpp", "example/src/foo.cpp", f"-o{output}"]

        assert not Path(output).exists()
        assert compile_locally(Arguments.from_vargs(*args), Host.localhost_with_limit(1)) == os.EX_OK
        assert Path(output).exists()

        executable_stdout: str = subprocess.check_output([f"./{output}"], encoding=ENCODING)
        assert executable_stdout == "homcc\n"

        Path(output).unlink(missing_ok=True)

        assert compile_locally(Arguments.from_vargs(*args, "-OError"), Host.localhost_with_limit(1)) != os.EX_OK
