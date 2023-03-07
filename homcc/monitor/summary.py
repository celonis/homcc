"""summarized statistics to keep track of files over time"""
from typing import Optional, Dict
from dataclasses import dataclass, field


@dataclass
class HostStats:
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
    filepath: str = field(hash=True)
    creation_time: int = field(hash=True)
    # phase: CompilationPhase  # might be unnecessary

    preprocessing_start: Optional[int] = None
    preprocessing_stop: Optional[int] = None
    compilation_start: Optional[int] = None
    compilation_stop: Optional[int] = None

    def get_compilation_time(self) -> int:
        if (self.compilation_start is None) or (self.compilation_stop is None):
            return -1
        return self.compilation_stop - self.compilation_start

    def get_preprocessing_time(self) -> int:
        if (self.preprocessing_stop is None) or (self.preprocessing_start is None):
            return -1
        return self.preprocessing_stop - self.preprocessing_start


class SummaryStats:
    """summarized statistics to not lose information about files over time"""
    # these two fields will be resettable in the future via the RESET button
    host_stats: Dict[str, HostStats] = {}
    file_stats: Dict[str, FileStats] = {}

    def register_compilation(self, filename: str, hostname: str, timestamp: int):
        # if new host add to dict and default its stats
        # track host stats
        if not (hostname in self.host_stats):
            self.host_stats[hostname] = HostStats(hostname)
        self.host_stats[hostname].register_compilation()

        # track file stats
        # only current
        self.file_stats[filename] = FileStats(filename, timestamp)

    def preprocessing_start(self, filename: str, timestamp: int):
        self.file_stats[filename].preprocessing_start = timestamp

    def preprocessing_stop(self, filename: str, timestamp: int):
        file_stat = self.file_stats[filename]
        if file_stat.preprocessing_start > timestamp:
            raise ValueError("Timestamp of preprocessing start cannot be after timestamp of preprocessing end!")
        file_stat.preprocessing_stop = timestamp

    # for now this would always be preprocessing stop time but this will change in the future once we know when the
    # "Send" phase is over
    def compilation_start(self, filename: str, timestamp: int):
        self.file_stats[filename].compilation_start = timestamp

    def compilation_stop(self, filename: str, timestamp: int):
        file_stat = self.file_stats[filename]
        if file_stat.compilation_start > timestamp:
            raise ValueError("Timestamp of compilation start cannot be after timestamp of compilation end!")
        file_stat.compilation_stop = timestamp

    def deregister_compilation(self, filename: str, hostname: str, timestamp: int):
        # deregister from hosts
        self.host_stats[hostname].deregister_compilation()
        # mark File as completed
        self.compilation_stop(filename, timestamp)
