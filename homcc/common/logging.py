"""Custom logging for the homcc client and server"""
from __future__ import annotations

import logging

from abc import ABC, abstractmethod
from enum import Enum, Flag, auto
from typing import Dict, Optional


class MissingLogFile(Exception):
    """Exception to indicate a missing logging file when FormatterDestination.FILE is specified."""


class Formatter(Enum):
    """Enum fields specifying whether to choose the ClientFormatter or ServerFormatter."""

    CLIENT = auto()
    SERVER = auto()


class FormatterConfig(Flag):
    """Flags to indicate whether a Formatter should display messages in detailed and/or colored mode."""

    NONE = 0
    COLORED = auto()
    DETAILED = auto()
    ALL = COLORED | DETAILED

    def is_none(self) -> bool:
        return self == self.NONE

    def is_colored(self) -> bool:
        return self & self.COLORED != self.NONE  # type: ignore

    def is_detailed(self) -> bool:
        return self & self.DETAILED != self.NONE  # type: ignore


class FormatterDestination(Enum):
    """Flags to indicate whether a Formatter should display messages to a stream and/or a specified file."""

    STREAM = auto()
    FILE = auto()


class _Formatter(ABC, logging.Formatter):
    """Base class for Client and Server specific log formatters"""

    # terminal color and formatting codes
    DEBUG: str = "\x1b[36;1m"  # 0x06989A: light blue, bold
    INFO: str = "\x1b[34;1m"  # 0x3465A4: dark blue, bold
    WARNING: str = "\x1b[33;1m"  # 0xC4A000 yellow, bold
    ERROR: str = "\x1b[31;1m"  # 0xCC0000: red, bold
    CRITICAL: str = "\x1b[41;1m"  # 0xCC0000: red background
    RESET: str = "\x1b[0m"  # reset formatting to default

    def __init__(self, config: FormatterConfig):
        super().__init__()

        self._config = config

        self._level_formats: Dict[int, str] = {
            logging.DEBUG: self._level_format(self.DEBUG),
            logging.INFO: self._level_format(self.INFO),
            logging.WARNING: self._level_format(self.WARNING),
            logging.ERROR: self._level_format(self.ERROR),
            logging.CRITICAL: self._level_format(self.CRITICAL),
        }

    @abstractmethod
    def _level_format(self, level_format: str) -> str:
        pass

    def format(self, record: logging.LogRecord):
        log_format: Optional[str] = self._level_formats.get(record.levelno)
        formatter: logging.Formatter = logging.Formatter(log_format)

        return formatter.format(record)


class _ClientFormatter(_Formatter):
    """
    Class to format logging messages on the client.
    Contrary to the ServerFormatter, the ClientFormatter introduces a HOMCC prefix to differentiate the origin of
    logging messages when included in other build systems and excludes logging timestamps
    """

    def _level_format(self, level_format: str) -> str:
        # TODO(s.pirsch): replace this with pattern matching in python3.10
        # colored logging messages with debug information
        if self._config.is_colored() and self._config.is_detailed():
            return f"[{level_format}HOMCC-%(levelname)s{self.RESET}] %(pathname)s:%(lineno)d:\n%(message)s"

        # uncolored logging messages with debug information
        if self._config.is_detailed():
            return "[HOMCC-%(levelname)s] %(pathname)s:%(lineno)d:\n%(message)s"

        # user-friendly, colored logging messages
        if self._config.is_colored():
            return f"[{level_format}HOMCC-%(levelname)s{self.RESET}] %(message)s"

        # user-friendly, uncolored logging messages
        if self._config.is_none():
            return "[HOMCC-%(levelname)s] %(message)s"

        raise ValueError(f"Unrecognized formatter configuration {self._config}")


class _ServerFormatter(_Formatter):
    """
    Class to format logging messages on the server.
    Contrary to the ClientFormatter, the ServerFormatter includes timestamp information in its detailed logging mode.
    """

    def _level_format(self, level_format: str) -> str:
        # TODO(s.pirsch): replace this with pattern matching in python3.10
        # colored logging messages with debug information
        if self._config.is_colored() and self._config.is_detailed():
            return f"[{level_format}%(levelname)s{self.RESET}] %(asctime)s - %(pathname)s:%(lineno)d:\n%(message)s"

        # uncolored logging messages with debug information
        if self._config.is_detailed():
            return "[%(levelname)s] %(asctime)s - %(pathname)s:%(lineno)d:\n%(message)s"

        # user-friendly, colored logging messages
        if self._config.is_colored():
            return f"[{level_format}%(levelname)s{self.RESET}] %(asctime)s - %(message)s"

        # user-friendly, uncolored logging messages
        if self._config.is_none():
            return "[%(levelname)s] %(asctime)s - %(message)s"

        raise ValueError(f"Unrecognized formatter configuration {self._config}")


def setup_logging(formatter: Formatter, config: FormatterConfig, destination: FormatterDestination, **kwargs):
    """
    Set up basic configuration for the logging system to display homcc messages on the client or the server.

    formatter   Specify either CLIENT to use a formatter designed for the Client or
                specify SERVER to use a formatter designed for the Server.
    config      Use COLORED for colored logging, e.g. for user-facing logging directly to console.
                Use DETAILED to include additional useful debugging information.
                Use ALL to enable all the above config options.
                Use NONE to enable none of the above config options.
    destination Use STREAM to log to console.
                Use FILE to log to a file specified in optional parameter "file_name".
    file_name   Optional: Used only if FormatterDestination.File was chosen, specify the logging file.
    level       Optional: Explicitly state the logging level [DEBUG, INFO, WARNING, ERROR, CRITICAL].
    """
    # default logging level in the logging library is logging.WARNING, but we use logging.INFO as default instead
    level: int = kwargs.pop("level", logging.INFO)
    filename: Optional[str] = kwargs.pop("filename", None)

    if kwargs:
        keys: str = ", ".join(kwargs.keys())
        raise ValueError(f"Unrecognised argument(s): {keys}")

    # initialize formatter to deduce the correct formatting strings
    fmt: _Formatter = _ClientFormatter(config) if formatter == Formatter.CLIENT else _ServerFormatter(config)

    # initialize handlers with the correct formatter
    handler: logging.Handler

    if destination == FormatterDestination.STREAM:
        handler = logging.StreamHandler()
        handler.setFormatter(fmt)

    elif destination == FormatterDestination.FILE:
        if not filename:
            raise MissingLogFile

        handler = logging.FileHandler(filename)
        handler.setFormatter(fmt)

    else:
        raise ValueError(f"Unrecognized formatter destination {destination}")

    # configure the root logger
    logging.basicConfig(level=level, handlers=[handler])
