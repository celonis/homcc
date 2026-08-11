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
    MAX_SUPPLEMENTAL_DEPENDENCIES_PER_PROFILE,
    SQLITE_WRITE_LOCK_ACQUISITIONS_STAT,
    SQLITE_WRITE_LOCK_WAIT_AVG_US_STAT,
    IncludeAnalyzer,
    PreprocessingCache,
    UnsupportedIncludeSyntax,
    analyze_dependencies,
    learn_supplemental_dependencies,
)
from homcc.common.arguments import Arguments


class TestPreprocessingCache:
    """Tests for persistent include analysis and hashing."""

    def test_reports_average_sqlite_write_lock_wait(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cache_path = tmp_path / "cache.sqlite3"
        cache = PreprocessingCache(cache_path)
        ticks = iter((1_000_000, 1_006_000))
        monkeypatch.setattr("homcc.client.preprocessing_cache.time.monotonic_ns", lambda: next(ticks))

        cache._begin_immediate()  # pylint: disable=protected-access
        cache.connection.execute("COMMIT")
        assert cache.pending_stats[SQLITE_WRITE_LOCK_ACQUISITIONS_STAT] == 1
        assert cache.pending_stats["sqlite_write_lock_wait_ns"] == 6_000

        # Restore the real clock before close() records its own acquisition.
        monkeypatch.undo()
        cache.close()
        stats = PreprocessingCache.stats(cache_path)
        assert stats[SQLITE_WRITE_LOCK_ACQUISITIONS_STAT] == 2
        assert stats[SQLITE_WRITE_LOCK_WAIT_AVG_US_STAT] >= 3

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

    def test_learns_supplemental_dependencies_across_translation_units(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        cache_dir = tmp_path / "cache"
        include_dir = tmp_path / "include"
        include_dir.mkdir()
        supplemental = include_dir / "generated.hpp"
        supplemental.write_text("#pragma once\n", encoding="utf-8")
        first_source = tmp_path / "first.cpp"
        second_source = tmp_path / "second.cpp"
        computed_include = "#if ENABLE_GENERATED\n#include BOOST_PP_ITERATE()\n#endif\n"
        first_source.write_text(computed_include, encoding="utf-8")
        second_source.write_text(computed_include, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOMCC_DIR", str(cache_dir))

        first_arguments = Arguments.from_vargs(
            "g++",
            "-DENABLE_GENERATED=1",
            f"-I{include_dir}",
            "-MD",
            "-MF",
            "first.d",
            "-o",
            "first.o",
            str(first_source),
        )
        first = analyze_dependencies(first_arguments)
        assert first is not None
        exact_dependencies = first.base_dependencies.copy()
        exact_dependencies[str(supplemental)] = "compiler-authored-hash"
        learn_supplemental_dependencies(first, exact_dependencies)

        second_arguments = Arguments.from_vargs(
            "g++",
            "-DENABLE_GENERATED=1",
            f"-I{include_dir}",
            "-MD",
            "-MF",
            "second.d",
            "-o",
            "second.o",
            str(second_source),
        )
        second = analyze_dependencies(second_arguments)

        assert second is not None
        assert second.profile == first.profile
        assert str(supplemental) not in second.base_dependencies
        assert str(supplemental) in second.dependencies
        different_flags = analyze_dependencies(
            Arguments.from_vargs("g++", "-DOTHER=1", f"-I{include_dir}", str(second_source))
        )
        assert different_flags is not None
        assert different_flags.profile != first.profile
        assert str(supplemental) not in different_flags.dependencies

        stats = PreprocessingCache.stats(cache_dir / "preprocessing-cache.sqlite3")
        assert stats["supplemental_profiles"] == 1
        assert stats["supplemental_dependencies"] == 1
        assert stats["supplemental_learns"] == 1
        assert stats["supplemental_learned_paths"] == 1
        assert stats["supplemental_hits"] == 1
        assert stats["supplemental_misses"] == 2

    def test_prunes_missing_supplemental_dependency(self, tmp_path: Path):
        cache_path = tmp_path / "cache.sqlite3"
        supplemental = tmp_path / "generated.hpp"
        supplemental.write_text("#pragma once\n", encoding="utf-8")
        with PreprocessingCache(cache_path) as cache:
            assert cache.learn_supplemental_dependencies("profile", {str(supplemental)}) == 1
        supplemental.unlink()

        with PreprocessingCache(cache_path) as cache:
            assert cache.supplemental_dependencies("profile") == set()

        stats = PreprocessingCache.stats(cache_path)
        assert stats["supplemental_pruned_paths"] == 1
        assert stats["supplemental_profiles"] == 0

    def test_rejects_complete_supplemental_set_over_profile_limit(self, tmp_path: Path):
        cache_path = tmp_path / "cache.sqlite3"
        dependencies = {
            str(tmp_path / f"generated-{index}.hpp") for index in range(MAX_SUPPLEMENTAL_DEPENDENCIES_PER_PROFILE + 1)
        }

        with PreprocessingCache(cache_path) as cache:
            assert cache.learn_supplemental_dependencies("profile", dependencies) == 0

        stats = PreprocessingCache.stats(cache_path)
        assert stats["supplemental_overflows"] == 1
        assert stats["supplemental_profiles"] == 0

    def test_parallel_supplemental_learners_preserve_union(self, tmp_path: Path):
        cache_path = tmp_path / "cache.sqlite3"
        dependencies = [tmp_path / "first.hpp", tmp_path / "second.hpp"]
        for dependency in dependencies:
            dependency.write_text("#pragma once\n", encoding="utf-8")

        def learn(dependency: Path):
            with PreprocessingCache(cache_path) as cache:
                cache.learn_supplemental_dependencies("profile", {str(dependency)})

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(learn, dependency) for dependency in dependencies]
            for future in futures:
                future.result()

        with PreprocessingCache(cache_path) as cache:
            assert cache.supplemental_dependencies("profile") == set(dependencies)

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

    def test_normalizes_parent_components_in_relative_includes(self, tmp_path: Path):
        include_dir = tmp_path / "include"
        base = include_dir / "base/config.h"
        variant = include_dir / "types/variant.h"
        internal_variant = include_dir / "types/internal/variant.h"
        source = tmp_path / "main.cpp"
        base.parent.mkdir(parents=True)
        internal_variant.parent.mkdir(parents=True)
        base.write_text("#pragma once\n", encoding="utf-8")
        internal_variant.write_text('#include "../../base/config.h"\n', encoding="utf-8")
        variant.write_text('#include "../base/config.h"\n#include "../types/internal/variant.h"\n', encoding="utf-8")
        source.write_text('#include "types/variant.h"\n', encoding="utf-8")
        arguments = Arguments.from_vargs("g++", f"-I{include_dir}", str(source))

        with PreprocessingCache(tmp_path / "cache.sqlite3") as cache:
            dependencies = IncludeAnalyzer(cache).analyze(arguments, cwd=tmp_path)

        assert set(dependencies) == {str(source), str(base), str(variant), str(internal_variant)}
        assert all(".." not in Path(dependency).parts for dependency in dependencies)

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
            cache.learn_supplemental_dependencies("profile", {str(source)})

        PreprocessingCache.clear(cache_path)

        stats = PreprocessingCache.stats(cache_path)
        assert stats["entries"] == 0
        assert stats["supplemental_profiles"] == 0
        assert stats["supplemental_dependencies"] == 0

    def test_evicts_old_entries_over_size_limit(self, tmp_path: Path):
        source = tmp_path / "main.c"
        source.write_text("int value;\n", encoding="utf-8")
        cache_path = tmp_path / "cache.sqlite3"

        with PreprocessingCache(cache_path, max_size_bytes=1) as cache:
            IncludeAnalyzer(cache).analyze(Arguments.from_vargs("gcc", str(source)), cwd=tmp_path)

        stats = PreprocessingCache.stats(cache_path)
        assert stats["entries"] == 0
        assert stats["evictions"] == 1

    def test_evicts_supplemental_profiles_over_size_limit(self, tmp_path: Path):
        dependency = tmp_path / "generated.hpp"
        dependency.write_text("#pragma once\n", encoding="utf-8")
        cache_path = tmp_path / "cache.sqlite3"

        with PreprocessingCache(cache_path, max_size_bytes=1) as cache:
            cache.learn_supplemental_dependencies("profile", {str(dependency)})

        stats = PreprocessingCache.stats(cache_path)
        assert stats["supplemental_profiles"] == 0
        assert stats["evictions"] == 1
