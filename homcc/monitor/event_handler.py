"""observer class to track state files"""
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from watchdog.events import FileSystemEvent, PatternMatchingEventHandler

from homcc.common.constants import ENCODING
from homcc.common.statefile import StateFile
from homcc.monitor.summary import SummaryStats

logger = logging.getLogger(__name__)


@dataclass
class CompilationInfo:
    """class to encapsulate all relevant compilation info"""

    hostname: str
    phase: str
    filename: str

    def __init__(self, statefile: StateFile):
        self.hostname = statefile.hostname.decode(ENCODING)
        self.phase = StateFile.ClientPhase(statefile.phase).name
        self.filename = statefile.source_base_filename.decode(ENCODING)

        logger.debug(
            "Created entry for hostname '%s' in Phase '%s' with source base filename '%s' ",
            self.hostname,
            self.phase,
            self.filename,
        )


class StateFileEventHandler(PatternMatchingEventHandler):
    """tracks state files and adds or removes state files into a list based on their creation or deletion"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.table_info: Dict[Path, CompilationInfo] = {}
        self.summary: SummaryStats = SummaryStats()
        self.finished_preprocessing_files: List[str] = []
        self.finished_compiling_files: List[str] = []

    @staticmethod
    def read_statefile(filepath: Path) -> Optional[StateFile]:
        """return read StateFile if existent and not empty"""

        try:
            if file_bytes := Path.read_bytes(filepath):
                return StateFile.from_bytes(file_bytes)
        except FileNotFoundError:
            logger.debug("File %s was deleted again before being read.", filepath)
        return None

    def _register_compilation(self, src_path: Path, state_file: StateFile, time_now_sec: float):
        compilation_info = CompilationInfo(state_file)
        self.table_info[src_path] = compilation_info
        self.summary.register_compilation(
            compilation_info.filename,
            compilation_info.hostname,
            time_now_sec,
        )

    def on_any_event(self, event: FileSystemEvent):
        if event.is_directory:
            return

        statefile = self.read_statefile(Path(event.src_path))

        # do nothing for moved, closed and opened events
        if event.event_type in ["moved", "opened", "closed"]:
            return

        time_now = datetime.now()
        time_now_in_ms = time_now.timestamp()

        logger.debug(
            "'%s' - '%s' has been %s!",
            time_now.strftime("%d/%m/%Y %H:%M:%S"),
            event.src_path,
            event.event_type,
        )

        # statefile does not exist anymore or deletion was detected
        if (not statefile or event.event_type == "deleted") and event.src_path in self.table_info:
            compilation_info = self.table_info.pop(event.src_path)
            # if the start or stop of preprocessing was skipped, we assume that the time was too short for measurement
            # and will therefore be visualized with 0s
            if (
                compilation_info.filename in self.summary.file_stats
                and self.summary.file_stats[compilation_info.filename].get_preprocessing_time() is None
            ):
                self.finished_preprocessing_files.append(compilation_info.filename)
            self.summary.deregister_compilation(compilation_info.filename, compilation_info.hostname, time_now_in_ms)
            self.finished_compiling_files.append(compilation_info.filename)
            return

        if statefile is None:
            return

        # statefile creation detected
        if event.event_type == "created":
            self._register_compilation(event.src_path, statefile, time_now_in_ms)
            if statefile.phase == StateFile.ClientPhase.CPP:
                self.summary.preprocessing_start(self.table_info[event.src_path].filename, time_now_in_ms)

        # statefile modification detected
        if event.event_type == "modified":
            # check if modification event is also a creation
            if event.src_path in self.table_info:
                prev_phase = self.table_info[event.src_path].phase
                next_phase = StateFile.ClientPhase(statefile.phase).name
                self.table_info[event.src_path].phase = next_phase
                if prev_phase == next_phase:
                    logger.debug("File %s was modified but stayed in phase %s", event.src_path, prev_phase)
                    return
            else:
                self._register_compilation(event.src_path, statefile, time_now_in_ms)
        compilation_info = self.table_info[event.src_path]
        # TODO(s.pirsch): check correct enum usage (type conversion)
        if statefile.phase == StateFile.ClientPhase.CPP.value:
            self.summary.preprocessing_start(compilation_info.filename, time_now_in_ms)
        elif statefile.phase == StateFile.ClientPhase.COMPILE.value:
            self.summary.preprocessing_stop(compilation_info.filename, time_now_in_ms)
            self.finished_preprocessing_files.append(compilation_info.filename)
            self.summary.compilation_start(compilation_info.filename, time_now_in_ms)
