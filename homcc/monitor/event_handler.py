"""observer class to track state files"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from watchdog.events import FileSystemEvent, PatternMatchingEventHandler

from homcc.common.constants import ENCODING
from homcc.common.statefile import StateFile
from homcc.monitor.summary import SummaryStats

logger = logging.getLogger(__name__)


@dataclass
class CompilationInfo:
    event_src_path: Path
    hostname: str
    phase: str
    file_path: str


class StateFileEventHandler(PatternMatchingEventHandler):
    """tracks state files and adds or removes state files into a list based on their creation or deletion"""
    summary: SummaryStats = SummaryStats()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.table_info: List[CompilationInfo] = []

    def on_created(self, event: FileSystemEvent):
        """tracks the creation of a state file and reads its data into table_info"""

        try:
            file = Path.read_bytes(Path(event.src_path))
        except FileNotFoundError:
            return

        if len(file) == 0:
            return

        state: StateFile = StateFile.from_bytes(file)

        compilation_info = CompilationInfo(
            event_src_path=event.src_path,
            hostname=state.hostname.decode(ENCODING),
            phase=StateFile.ClientPhase(state.phase).name,
            file_path=state.source_base_filename.decode(ENCODING),
        )
        self.table_info.append(compilation_info)

        logger.debug(
            "Created entry for hostname '%s' in Phase '%s' with source base filename '%s' ",
            state.hostname.decode(ENCODING),
            StateFile.ClientPhase(state.phase).name,
            state.source_base_filename,
        )

        time_stamp = datetime.now()
        logger.debug("'%s' - '%s' has been created!", time_stamp.strftime('%d/%m/%Y %H:%M:%S'), event.src_path)

        self.summary.register_compilation(int(time_stamp.timestamp()), compilation_info.hostname, 
                                          compilation_info.file_path)

    def on_deleted(self, event: FileSystemEvent):
        """tracks deletion of a state file - not actively used"""

        logger.debug("'%s' - '%s' has been deleted!", datetime.now().strftime('%d/%m/%Y %H:%M:%S'), event.src_path)

        self.table_info = [e for e in self.table_info if e.event_src_path != event.src_path]

    @staticmethod
    def on_modified(event: FileSystemEvent):
        """tracks modification of a state file - not actively used"""

        logger.debug("'%s' - '%s' has been modified!", datetime.now().strftime('%d/%m/%Y %H:%M:%S'), event.src_path)

    @staticmethod
    def on_moved(event: FileSystemEvent):
        """tracks path movement of a state file - not actively used"""

        logger.debug("'%s' - '%s' has been moved!", datetime.now().strftime('%d/%m/%Y %H:%M:%S'), event.src_path)
