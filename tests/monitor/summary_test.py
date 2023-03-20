"""Tests regarding the summary stats module of homcc."""
from homcc.monitor.summary import SummaryStats


class TestSummaryStats:
    """Tests for summary.py"""

    def test_register_compilation(self):
        summary = SummaryStats()

        summary.register_compilation("main.cpp", "remotehost:1337", 1_000_000)
        assert len(summary.host_stats) == 1
        assert len(summary.file_stats) == 1
        assert summary.host_stats["remotehost:1337"].current_compilations == 1
        assert summary.host_stats["remotehost:1337"].total_compilations == 1
        assert summary.file_stats["main.cpp"].creation_time == 1_000_000

    def test_register_same_file_twice(self):
        summary = SummaryStats()

        summary.register_compilation("foo.cpp", "localhost", 0)
        summary.compilation_start("foo.cpp", 0)
        assert len(summary.host_stats) == 1
        assert len(summary.file_stats) == 1
        assert summary.host_stats["localhost"].current_compilations == 1
        assert summary.host_stats["localhost"].total_compilations == 1
        assert summary.file_stats["foo.cpp"].creation_time == 0

        summary.register_compilation("foo2.cpp", "localhost", 1)
        assert len(summary.host_stats) == 1
        assert len(summary.file_stats) == 2
        assert summary.host_stats["localhost"].current_compilations == 2
        assert summary.host_stats["localhost"].total_compilations == 2
        assert summary.file_stats["foo2.cpp"].creation_time == 1

        summary.deregister_compilation("foo.cpp", "localhost", 1)

        summary.register_compilation("foo.cpp", "localhost", 2)
        assert len(summary.host_stats) == 1
        assert len(summary.file_stats) == 2
        assert summary.host_stats["localhost"].current_compilations == 2
        assert summary.host_stats["localhost"].total_compilations == 3
        assert summary.file_stats["foo.cpp"].creation_time == 2

    def test_deregister_compilations(self):
        summary = SummaryStats()
        summary.register_compilation("foo.cpp", "localhost", 0)
        summary.compilation_start("foo.cpp", 0)
        assert len(summary.host_stats) == 1
        assert len(summary.file_stats) == 1
        assert summary.host_stats["localhost"].current_compilations == 1
        assert summary.host_stats["localhost"].total_compilations == 1
        summary.deregister_compilation("foo.cpp", "localhost", 1)
        assert len(summary.host_stats) == 1
        assert len(summary.file_stats) == 1
        assert summary.host_stats["localhost"].current_compilations == 0
        assert summary.host_stats["localhost"].total_compilations == 1

    def test_time_measures(self):
        summary = SummaryStats()
        summary.register_compilation("foo.cpp", "localhost", 0)

        summary.preprocessing_stop("foo.cpp", 3)
        assert summary.file_stats["foo.cpp"].preprocessing_stop == summary.file_stats["foo.cpp"].preprocessing_start
        assert summary.file_stats["foo.cpp"].get_preprocessing_time() == 0
        foo_start_pre = 0
        summary.preprocessing_start("foo.cpp", foo_start_pre)
        summary.preprocessing_stop("foo.cpp", foo_start_pre + 1)
        assert summary.file_stats["foo.cpp"].preprocessing_start == foo_start_pre
        summary.preprocessing_stop("foo.cpp", foo_start_pre - 1)
        assert summary.file_stats["foo.cpp"].preprocessing_stop == -1
        assert summary.file_stats["foo.cpp"].get_preprocessing_time() == -1

        summary.compilation_stop("foo.cpp", 3)
        assert summary.file_stats["foo.cpp"].compilation_stop == summary.file_stats["foo.cpp"].compilation_start
        assert summary.file_stats["foo.cpp"].get_compilation_time() == 0
        foo_start_comp = foo_start_pre + 2
        summary.compilation_start("foo.cpp", foo_start_comp)
        summary.compilation_stop("foo.cpp", foo_start_comp + 1)
        assert summary.file_stats["foo.cpp"].compilation_start == foo_start_comp
        summary.compilation_stop("foo.cpp", foo_start_comp - 1)
        assert summary.file_stats["foo.cpp"].compilation_stop == foo_start_comp - 1
        assert summary.file_stats["foo.cpp"].get_compilation_time() == -1
