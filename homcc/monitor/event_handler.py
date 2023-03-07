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
    hostname: str
    phase: str
    file_path: str


class StateFileEventHandler(PatternMatchingEventHandler):
    """tracks state files and adds or removes state files into a list based on their creation or deletion"""
    summary: SummaryStats = SummaryStats()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.table_info: Dict[Path, CompilationInfo] = {}

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
            return None

        elif event.event_type == "created":
            try:
                file = Path.read_bytes(Path(event.src_path))
            except FileNotFoundError:
                return

            if len(file) == 0:
                return

            state: StateFile = StateFile.from_bytes(file)

            compilation_info = CompilationInfo(
                hostname=state.hostname.decode(ENCODING),
                phase=StateFile.ClientPhase(state.phase).name,
                file_path=state.source_base_filename.decode(ENCODING),
            )
            self.table_info[event.src_path] = compilation_info

            logger.debug(
                "Created entry for hostname '%s' in Phase '%s' with source base filename '%s' ",
                state.hostname.decode(ENCODING),
                StateFile.ClientPhase(state.phase).name,
                state.source_base_filename,
            )

            time_stamp = datetime.now()
            logger.debug("'%s' - '%s' has been created!", time_stamp.strftime("%d/%m/%Y %H:%M:%S"), event.src_path)

            self.summary.register_compilation(
                compilation_info.file_path, compilation_info.hostname, int(time_stamp.timestamp())
            )

        elif event.event_type == "modified":
            # tracks modification of a state file

            if statefile := self.read_statefile(Path(event.src_path)) and self.table_info.get(event.src_path):
                self.table_info[event.src_path].phase = statefile.phase
            else:
                # file was already deleted
                self.table_info.pop(event.src_path, None)

            logger.debug("'%s' - '%s' has been modified!", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), event.src_path)

        elif event.event_type == "deleted":
            # tracks deletion of a state file

            self.table_info.pop(event.src_path, None)
            logger.debug("'%s' - '%s' has been deleted!", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), event.src_path)
