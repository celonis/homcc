# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Tests for the client-side preprocessing cache."""

import json
import sqlite3
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
    """Tests for persistent include analysis and hashing."""

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

    def test_defers_missing_quoted_includes_in_conditional_branches(self, tmp_path: Path):
        source = tmp_path / "main.cpp"
        source.write_text(
            """
#if FIRST
#include "first.h"
#elif SECOND
#include "second.h"
#else
#ifndef THIRD
#include "third.h"
#endif
#endif
""",
            encoding="utf-8",
        )
        arguments = Arguments.from_vargs("g++", str(source))

        with PreprocessingCache(tmp_path / "cache.sqlite3") as cache:
            dependencies = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

        assert set(dependencies) == {str(source)}

    def test_defers_starrocks_stl_msvc_include(self, tmp_path: Path):
        source = tmp_path / "main.cpp"
        port = tmp_path / "port.h"
        source.write_text('#include "port.h"\n', encoding="utf-8")
        port.write_text('#ifdef STL_MSVC\n#include "base/port_hash.h"\n#endif\n', encoding="utf-8")
        arguments = Arguments.from_vargs("g++", str(source))

        with PreprocessingCache(tmp_path / "cache.sqlite3") as cache:
            dependencies = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

        assert set(dependencies) == {str(source), str(port)}

    def test_propagates_conditional_context_to_transitive_includes(self, tmp_path: Path):
        source = tmp_path / "main.cpp"
        optional = tmp_path / "optional.h"
        source.write_text('#ifdef OPTIONAL\n#include "optional.h"\n#endif\n', encoding="utf-8")
        optional.write_text('#include "missing.h"\n', encoding="utf-8")
        arguments = Arguments.from_vargs("g++", str(source))

        with PreprocessingCache(tmp_path / "cache.sqlite3") as cache:
            dependencies = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

        assert set(dependencies) == {str(source), str(optional)}

    def test_reanalyzes_conditionally_visited_header_when_reached_unconditionally(self, tmp_path: Path):
        source = tmp_path / "main.cpp"
        shared = tmp_path / "shared.h"
        source.write_text('#include "shared.h"\n#ifdef OPTIONAL\n#include "shared.h"\n#endif\n', encoding="utf-8")
        shared.write_text('#include "project/missing.h"\n', encoding="utf-8")
        arguments = Arguments.from_vargs("g++", str(source))

        with PreprocessingCache(tmp_path / "cache.sqlite3") as cache:
            with pytest.raises(UnsupportedIncludeSyntax):
                IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

    def test_missing_unconditional_quoted_include_requires_compiler_fallback(self, tmp_path: Path):
        source = tmp_path / "main.cpp"
        source.write_text('#include "project/missing.h"\n', encoding="utf-8")
        arguments = Arguments.from_vargs("g++", str(source))

        with PreprocessingCache(tmp_path / "cache.sqlite3") as cache:
            with pytest.raises(UnsupportedIncludeSyntax):
                IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

    def test_ignores_unresolved_quoted_system_header_basenames(self, tmp_path: Path):
        source = tmp_path / "main.cpp"
        source.write_text('#include "malloc.h"\n#include "typeinfo"\n', encoding="utf-8")
        arguments = Arguments.from_vargs("g++", str(source))

        with PreprocessingCache(tmp_path / "cache.sqlite3") as cache:
            dependencies = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

        assert set(dependencies) == {str(source)}

    def test_comment_markers_in_line_comments_do_not_hide_conditionals(self, tmp_path: Path):
        source = tmp_path / "main.cpp"
        source.write_text(
            """
// Match paths such as "*/foo/bar/*=2".
#if INNER
#define VALUE 1 /* close a real block comment */
#else
#define VALUE 2
#endif
""",
            encoding="utf-8",
        )
        arguments = Arguments.from_vargs("g++", str(source))

        with PreprocessingCache(tmp_path / "cache.sqlite3") as cache:
            dependencies = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

        assert set(dependencies) == {str(source)}

    def test_computed_include_requires_compiler_fallback(self, tmp_path: Path):
        source = tmp_path / "main.cpp"
        source.write_text("#include UNKNOWN_HEADER\n", encoding="utf-8")
        arguments = Arguments.from_vargs("g++", str(source))

        with PreprocessingCache(tmp_path / "cache.sqlite3") as cache:
            with pytest.raises(UnsupportedIncludeSyntax):
                IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

    def test_resolves_boost_header_alias_macros(self, tmp_path: Path):
        include_dir = tmp_path / "include"
        iterate = include_dir / "boost/preprocessor/iterate.hpp"
        user_config = include_dir / "boost/config/user.hpp"
        iterate.parent.mkdir(parents=True)
        user_config.parent.mkdir(parents=True)
        iterate.write_text("#pragma once\n", encoding="utf-8")
        user_config.write_text("#pragma once\n", encoding="utf-8")
        source = tmp_path / "main.cpp"
        source.write_text(
            """
#if defined(BOOST_TT_PREPROCESSING_MODE)
#define PP1 <boost/preprocessor/iterate.hpp>
#include PP1
#endif
#if !defined(BOOST_USER_CONFIG) && !defined(BOOST_NO_USER_CONFIG)
#define BOOST_USER_CONFIG <boost/config/user.hpp>
#endif
#if defined(BOOST_USER_CONFIG)
#include BOOST_USER_CONFIG
#endif
""",
            encoding="utf-8",
        )
        arguments = Arguments.from_vargs("g++", f"-I{include_dir}", str(source))

        with PreprocessingCache(tmp_path / "cache.sqlite3") as cache:
            dependencies = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

        assert set(dependencies) == {str(source), str(iterate), str(user_config)}

    def test_defers_unknown_computed_include_in_conditional_branch(self, tmp_path: Path):
        source = tmp_path / "main.cpp"
        preprocessed = tmp_path / "preprocessed.hpp"
        preprocessed.write_text("#pragma once\n", encoding="utf-8")
        source.write_text(
            """
#if !defined(BOOST_NUMERIC_CONVERSION_DONT_USE_PREPROCESSED_FILES)
#include "preprocessed.hpp"
#else
#include BOOST_PP_ITERATE()
#endif
""",
            encoding="utf-8",
        )
        arguments = Arguments.from_vargs("g++", str(source))

        with PreprocessingCache(tmp_path / "cache.sqlite3") as cache:
            dependencies = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

        assert set(dependencies) == {str(source), str(preprocessed)}

    @pytest.mark.parametrize(
        "source_text",
        (
            "#else\n",
            "#endif\n",
            "#if VALUE\n#else\n#else\n#endif\n",
            "#if VALUE\n#else\n#elif OTHER\n#endif\n",
            "#if VALUE\n",
        ),
    )
    def test_malformed_conditionals_require_compiler_fallback(self, tmp_path: Path, source_text: str):
        source = tmp_path / "main.cpp"
        source.write_text(source_text, encoding="utf-8")
        arguments = Arguments.from_vargs("g++", str(source))

        with PreprocessingCache(tmp_path / "cache.sqlite3") as cache:
            with pytest.raises(UnsupportedIncludeSyntax):
                IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

    def test_reparses_legacy_directive_records_without_invalidating_sha1(self, tmp_path: Path):
        source = tmp_path / "main.cpp"
        source.write_text('#ifdef OPTIONAL\n#include "missing.h"\n#endif\n', encoding="utf-8")
        arguments = Arguments.from_vargs("g++", str(source))
        cache_path = tmp_path / "cache.sqlite3"
        with PreprocessingCache(cache_path) as cache:
            dependencies = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)
        original_sha1 = dependencies[str(source)]

        connection = sqlite3.connect(str(cache_path))
        try:
            connection.execute(
                "UPDATE files SET directives = ? WHERE path = ?",
                (json.dumps([["include", "missing.h", True]]), str(source)),
            )
            connection.commit()
        finally:
            connection.close()

        with PreprocessingCache(cache_path) as cache:
            migrated = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

        connection = sqlite3.connect(str(cache_path))
        try:
            encoded, cached_sha1 = connection.execute(
                "SELECT directives, sha1 FROM files WHERE path = ?", (str(source),)
            ).fetchone()
        finally:
            connection.close()
        assert json.loads(encoded)["version"] == 3
        assert cached_sha1 == original_sha1
        assert migrated[str(source)] == original_sha1

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
