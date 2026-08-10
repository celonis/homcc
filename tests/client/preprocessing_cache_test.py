# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Tests for the client-side preprocessing cache."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from homcc.client.preprocessing_cache import (
    IncludeAnalyzer,
    PreprocessingCache,
    UnsupportedIncludeSyntax,
)
from homcc.common.arguments import Arguments


class TestPreprocessingCache:
    def test_analyzes_and_reuses_literal_include_graph(self, tmp_path: Path):
        include_dir = tmp_path / "include"
        include_dir.mkdir()
        source = tmp_path / "main.cpp"
        shared = include_dir / "shared.h"
        nested = include_dir / "nested.h"
        source.write_text('#include "shared.h"\nint main() {}\n', encoding="utf-8")
        shared.write_text('#include "nested.h"\n', encoding="utf-8")
        nested.write_text("#define VALUE 1\n", encoding="utf-8")
        arguments = Arguments.from_vargs("g++", f"-I{include_dir}", str(source))

        cache_path = tmp_path / "cache.sqlite3"
        with PreprocessingCache(cache_path) as cache:
            first = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)
        with PreprocessingCache(cache_path) as cache:
            second = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

        assert first == second
        assert set(first) == {str(source), str(shared), str(nested)}
        stats = PreprocessingCache.stats(cache_path)
        assert stats["directives_misses"] == 3
        assert stats["sha1_misses"] == 3
        assert stats["directives_hits"] == 3
        assert stats["sha1_hits"] == 3

    def test_invalidates_changed_file(self, tmp_path: Path):
        source = tmp_path / "main.cpp"
        source.write_text("int value = 1;\n", encoding="utf-8")
        arguments = Arguments.from_vargs("g++", str(source))
        cache_path = tmp_path / "cache.sqlite3"

        with PreprocessingCache(cache_path) as cache:
            first = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)
        source.write_text("int value = 123456;\n", encoding="utf-8")
        with PreprocessingCache(cache_path) as cache:
            second = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

        assert first[str(source)] != second[str(source)]

    def test_parallel_analyzers_share_per_file_work(self, tmp_path: Path):
        header = tmp_path / "shared.h"
        source = tmp_path / "main.cpp"
        header.write_text("#define VALUE 1\n", encoding="utf-8")
        source.write_text('#include "shared.h"\n', encoding="utf-8")
        cache_path = tmp_path / "cache.sqlite3"
        arguments = Arguments.from_vargs("g++", str(source))

        def analyze():
            with PreprocessingCache(cache_path) as cache:
                return IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(analyze) for _ in range(2)]
            results = [future.result() for future in futures]

        assert results[0] == results[1]
        stats = PreprocessingCache.stats(cache_path)
        assert stats["directives_misses"] == 2
        assert stats["sha1_misses"] == 2
        assert stats["directives_hits"] == 2
        assert stats["sha1_hits"] == 2

    def test_computed_include_requires_compiler_fallback(self, tmp_path: Path):
        source = tmp_path / "main.cpp"
        source.write_text("#define HEADER <vector>\n#include HEADER\n", encoding="utf-8")
        arguments = Arguments.from_vargs("g++", str(source))

        with PreprocessingCache(tmp_path / "cache.sqlite3") as cache:
            with pytest.raises(UnsupportedIncludeSyntax):
                IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

    def test_clear(self, tmp_path: Path):
        source = tmp_path / "main.c"
        source.write_text("int value;\n", encoding="utf-8")
        cache_path = tmp_path / "cache.sqlite3"
        with PreprocessingCache(cache_path) as cache:
            IncludeAnalyzer(cache).analyze(Arguments.from_vargs("gcc", str(source)), cwd=tmp_path)

        PreprocessingCache.clear(cache_path)

        assert PreprocessingCache.stats(cache_path)["entries"] == 0

    def test_evicts_old_entries_over_size_limit(self, tmp_path: Path):
        source = tmp_path / "main.c"
        source.write_text("int value;\n", encoding="utf-8")
        cache_path = tmp_path / "cache.sqlite3"

        with PreprocessingCache(cache_path, max_size_bytes=1) as cache:
            IncludeAnalyzer(cache).analyze(Arguments.from_vargs("gcc", str(source)), cwd=tmp_path)

        stats = PreprocessingCache.stats(cache_path)
        assert stats["entries"] == 0
        assert stats["evictions"] == 1
