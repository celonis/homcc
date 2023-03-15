"""summarized statistics to keep track of files over time"""
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class HostStats:
    """summarized statistics of hosts"""

    name: str
    current_compilations: int = 0
    total_compilations: int = 0
    # failed: int  # ignore this field for now

    def register_compilation(self):
        self.current_compilations += 1
        self.total_compilations += 1

    def deregister_compilation(self):
        self.current_compilations -= 1


@dataclass
class FileStats:
    """summarized statistics of files"""

    filepath: str = field(hash=True)
    creation_time: float = field(hash=True)

    preprocessing_start: Optional[float] = None
    preprocessing_stop: Optional[float] = None
    compilation_start: Optional[float] = None
    compilation_stop: Optional[float] = None

    def get_compilation_time(self) -> Optional[int]:
        if self.compilation_start is None or self.compilation_stop is None:
            return None
        return int(self.compilation_stop - self.compilation_start)

    def get_preprocessing_time(self) -> Optional[int]:
        if self.preprocessing_start is None or self.preprocessing_stop is None:
            return None
        return int(self.preprocessing_stop - self.preprocessing_start)


class SummaryStats:
    """summarized statistics to not lose information about files over time"""

    def __init__(self):
        self.host_stats: Dict[str, HostStats] = {}
        self.file_stats: Dict[str, FileStats] = {}

    def get_file_stat(self, filename: str) -> FileStats:
        # necessary because some files are created to fast and the creation is not tracked properly
        if filename in self.file_stats:
            return self.file_stats[filename]
        return FileStats(filename, 0)

    def register_compilation(self, filename: str, hostname: str, timestamp: float):
        # if new host, add to dict and default its stats
        if hostname not in self.host_stats:
            self.host_stats[hostname] = HostStats(hostname)
        self.host_stats[hostname].register_compilation()

        # track current file stats
        self.file_stats[filename] = FileStats(filename, timestamp)

    def preprocessing_start(self, filename: str, timestamp: float):
        self.file_stats[filename].preprocessing_start = timestamp

    def preprocessing_stop(self, filename: str, timestamp: float):
        file_stat = self.file_stats[filename]
        if file_stat.preprocessing_start is None:
            file_stat.preprocessing_start = timestamp
            logger.info("Preprocessing start timestamp was invalid, assuming zero duration")
        file_stat.preprocessing_stop = timestamp

    # for now this would always be preprocessing stop time but this will change in the future once we know when the
    # "Send" phase is over
    def compilation_start(self, filename: str, timestamp: float):
        self.file_stats[filename].compilation_start = timestamp

    def compilation_stop(self, filename: str, timestamp: float):
        file_stat = self.file_stats[filename]
        if file_stat.compilation_start is None:
            file_stat.compilation_start = timestamp
            if file_stat.get_preprocessing_time() is None:
                self.preprocessing_stop(filename, timestamp)
                logger.info("Preprocessing time was invalid, assuming zero duration")
            logger.info("Compilation start timestamp was invalid, assuming zero duration")
        file_stat.compilation_stop = timestamp

    def deregister_compilation(self, filename: str, hostname: str, timestamp: float):
        if filename not in self.file_stats:
            logger.info(
                "Tried to deregister compilation with filename '%s' which was not registered before. Ignoring it.",
                filename,
            )
            return
        # deregister from hosts
        self.host_stats[hostname].deregister_compilation()
        # mark File as completed
        self.compilation_stop(filename, timestamp)
