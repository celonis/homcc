
from pathlib import Path
from typing import Optional


class HostStats:

    name: str
    current_compilations: int
    total_compilations: int
    # failed: int  # ignore this field for now

    def __init__(self, name: str, current_compilations: int = 0, total_compilations: int = 0):
        self.name = name
        self.current_compilations = current_compilations
        self.total_compilations = total_compilations

    def register_compilation(self):
        self.current_compilations += 1
        self.total_compilations += 1

    def deregister_compilation(self):
        self.current_compilations -= 1


class FileStats:

    filepath: str
    creation_time: int
    # phase: CompilationPhase  # might be unnecessary

    preprocessing_start: Optional[int]
    preprocessing_stop: Optional[int]
    compilation_start: Optional[int]
    compilation_stop: Optional[int]

    def __init__(self, filepath: str, creation_time: int):
        self.filepath = filepath
        self.creation_time = creation_time

    def __hash__(self):
        return hash((self.filepath, self.creation_time))

    def get_compilation_time(self) -> int:
        return self.compilation_stop - self.compilation_start

    def get_preprocessing_time(self) -> int:
        return self.preprocessing_stop - self.preprocessing_start


class SummaryStats:
    # these two fields will be resettable in the future via the RESET button
    host_stats: dict[str, HostStats] = {}
    file_stats: dict[str, FileStats] = {}

    def register_compilation(self, time_stamp: int, host: str, file: str):
        # if new host add to dict and default its stats
        # track host stats
        if not (host in self.host_stats):
            self.host_stats[host] = HostStats(host)
        self.host_stats[host].register_compilation()

        # track file stats
        # only current
        self.file_stats[file] = FileStats(file, time_stamp)

    def preprocessing_start(self, time_stamp: int, file: str):
        self.file_stats[file].preprocessing_start = time_stamp

    def preprocessing_stop(self, time_stamp: int, file: str):
        file_stat = self.file_stats[file]
        if file_stat.preprocessing_start > time_stamp:
            raise ValueError("Timestamp of preprocessing start cannot be after timestamp of preprocessing end!")
        file_stat.preprocessing_stop = time_stamp

    # for now this would always be preprocessing stop time but this will change in the future once we know when the
    # "Send" phase is over
    def compilation_start(self, time_stamp: int, file: str):
        self.file_stats[file].compilation_start = time_stamp

    def compilation_stop(self, time_stamp: int, file: str):
        file_stat = self.file_stats[file]
        if file_stat.compilation_start > time_stamp:
            raise ValueError("Timestamp of compilation start cannot be after timestamp of compilation end!")
        file_stat.compilation_stop = time_stamp

    def deregister_compilation(self, time_stamp: int, host, file: str):
        # deregister from hosts
        self.host_stats[host].deregister_compilation()
        # mark File as completed
        self.compilation_stop(time_stamp, file)
