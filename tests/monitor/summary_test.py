"""Tests regarding the summary stats module of homcc."""
import time

import pytest

from homcc.monitor.summary import SummaryStats
from datetime import datetime


class TestSummaryStats:
    def test_register_compilation(self):
        summary = SummaryStats()

        summary.register_compilation(1000000, "remote-server.de:1337", "main.cpp")
        assert len(summary.host_stats) == 1
        assert len(summary.file_stats) == 1
        assert summary.host_stats["remote-server.de:1337"].current_compilations == 1
        assert summary.host_stats["remote-server.de:1337"].total_compilations == 1
        assert summary.file_stats["main.cpp"].creation_time == 1000000

    def test_register_same_file_twice(self):
        summary = SummaryStats()

        summary.register_compilation(0, "localhost", "foo.cpp")
        assert len(summary.host_stats) == 1
        assert len(summary.file_stats) == 1
        assert summary.host_stats["localhost"].current_compilations == 1
        assert summary.host_stats["localhost"].total_compilations == 1
        assert summary.file_stats["foo.cpp"].creation_time == 0

        summary.register_compilation(1, "localhost", "foo2.cpp")
        assert len(summary.host_stats) == 1
        assert len(summary.file_stats) == 2
        assert summary.host_stats["localhost"].current_compilations == 2
        assert summary.host_stats["localhost"].total_compilations == 2
        assert summary.file_stats["foo2.cpp"].creation_time == 1

        summary.deregister_compilation(1, "localhost", "foo.cpp")

        summary.register_compilation(2, "localhost", "foo.cpp")
        assert len(summary.host_stats) == 1
        assert len(summary.file_stats) == 2
        assert summary.host_stats["localhost"].current_compilations == 2
        assert summary.host_stats["localhost"].total_compilations == 3
        assert summary.file_stats["foo.cpp"].creation_time == 2

    def test_deregister_compilations(self):
        summary = SummaryStats()
        summary.register_compilation(int(datetime.now().timestamp()), "localhost", "foo.cpp")
        assert len(summary.host_stats) == 1
        assert len(summary.file_stats) == 1
        assert summary.host_stats["localhost"].current_compilations == 1
        assert summary.host_stats["localhost"].total_compilations == 1
        summary.deregister_compilation(int(datetime.now().timestamp()), "localhost", "foo.cpp")
        assert len(summary.host_stats) == 1
        assert len(summary.file_stats) == 1
        assert summary.host_stats["localhost"].current_compilations == 0
        assert summary.host_stats["localhost"].total_compilations == 1

    def test_time_measures(self):
        summary = SummaryStats()
        summary.register_compilation(int(datetime.now().timestamp()), "localhost", "foo.cpp")

        foo_start_comp = int(datetime.now().timestamp())
        summary.compilation_start(foo_start_comp, "foo.cpp")
        foo_stop_comp = foo_start_comp + 1
        summary.compilation_stop(foo_stop_comp, "foo.cpp")
        assert summary.file_stats["foo.cpp"].compilation_start == foo_start_comp
        with pytest.raises(
            ValueError, match=r"Timestamp of compilation start cannot be after timestamp of compilation end!"
        ):
            summary.compilation_stop(foo_start_comp - 1, "foo.cpp")
        assert summary.file_stats["foo.cpp"].compilation_stop == foo_stop_comp
        assert summary.file_stats["foo.cpp"].get_compilation_time() == 1

        foo_start_pre = foo_start_comp + 2
        summary.preprocessing_start(foo_start_pre, "foo.cpp")
        foo_stop_pre = foo_start_pre + 1
        summary.preprocessing_stop(foo_stop_pre, "foo.cpp")
        assert summary.file_stats["foo.cpp"].preprocessing_start == foo_start_pre
        with pytest.raises(
            ValueError, match=r"Timestamp of preprocessing start cannot be after timestamp of preprocessing end!"
        ):
            summary.preprocessing_stop(foo_start_pre - 1, "foo.cpp")
        assert summary.file_stats["foo.cpp"].preprocessing_stop == foo_stop_pre
        assert summary.file_stats["foo.cpp"].get_preprocessing_time() == 1
