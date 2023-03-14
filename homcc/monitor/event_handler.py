"""observer class to track state files"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

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
        self.finished_preprocessing_files: bool = False
        self.finished_compiling_files: bool = False

    @staticmethod
    def read_statefile(filepath: Path) -> Optional[StateFile]:
        """return read StateFile if existent and not empty"""

        try:
            if file_bytes := Path.read_bytes(filepath):
                return StateFile.from_bytes(file_bytes)
        except FileNotFoundError:
            logger.debug("File %s was deleted again before being read.", filepath)
        return None

    def on_any_event(self, event: FileSystemEvent):
        if event.is_directory:
            return

        statefile = self.read_statefile(Path(event.src_path))

        # do nothing for moved events
        if event.event_type == "moved":
            return

        time_stamp = datetime.now()

        logger.debug(
            "'%s' - '%s' has been %s!",
            time_stamp.strftime("%d/%m/%Y %H:%M:%S"),
            event.src_path,
            event.event_type,
        )

        # statefile does not exist anymore or deletion was detected
        if not statefile or event.event_type == "deleted":
            compilation_info = self.table_info[event.src_path]
            self.summary.deregister_compilation(
                compilation_info.filename, compilation_info.hostname, int(time_stamp.timestamp())
            )
            self.table_info.pop(event.src_path, None)
            return

        # statefile creation detected
        if event.event_type == "created":
            self.table_info[event.src_path] = CompilationInfo(statefile)
            self.summary.register_compilation(
                self.table_info[event.src_path].filename,
                self.table_info[event.src_path].hostname,
                int(time_stamp.timestamp()),
            )
            return

        # statefile modification detected
        if event.event_type == "modified":
            # check if modification event is also a creation
            compilation_info = self.table_info[event.src_path]
            timestamp_now = int(time_stamp.timestamp())
            if statefile.phase == StateFile.ClientPhase.COMPILE.name:
                self.summary.preprocessing_stop(compilation_info.filename, timestamp_now)
                self.finished_preprocessing_files = True
                self.summary.compilation_start(compilation_info.filename, timestamp_now)
            elif statefile.phase == StateFile.ClientPhase.CPP.name:
                self.summary.preprocessing_start(compilation_info.filename, timestamp_now)
            if event.src_path in self.table_info:
                self.table_info[event.src_path].phase = StateFile.ClientPhase(statefile.phase).name
            else:
                self.table_info[event.src_path] = CompilationInfo(statefile)
