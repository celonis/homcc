# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Tests regarding the logging module of homcc."""
import pytest

from homcc.common.logging import (
    Formatter,
    FormatterConfig,
    FormatterDestination,
    LoggingConfig,
    LogLevel,
    MissingLogFileError,
    setup_logging,
)


class TestLogging:
    """Tests for common/logging.py"""

    def test_formatter_config(self):
        assert FormatterConfig.NONE.is_none()
        assert not FormatterConfig.NONE.is_colored()
        assert not FormatterConfig.NONE.is_detailed()

        assert not FormatterConfig.COLORED.is_none()
        assert FormatterConfig.COLORED.is_colored()
        assert not FormatterConfig.COLORED.is_detailed()

        assert not FormatterConfig.DETAILED.is_none()
        assert not FormatterConfig.DETAILED.is_colored()
        assert FormatterConfig.DETAILED.is_detailed()

        assert not FormatterConfig.ALL.is_none()
        assert FormatterConfig.ALL.is_colored()
        assert FormatterConfig.ALL.is_detailed()

        # check whether ALL flag really includes all flags, sanity check if we decide to expand FormatterConfig
        for flag in FormatterConfig.__members__.values():
            assert FormatterConfig.ALL | flag == FormatterConfig.ALL

    def test_missing_log_file(self):
        with pytest.raises(MissingLogFileError):
            setup_logging(
                LoggingConfig(
                    formatter=Formatter.CLIENT,
                    config=FormatterConfig.ALL,
                    destination=FormatterDestination.FILE,
                    level=LogLevel.INFO,
                )
            )
