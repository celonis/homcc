"""observer class to track state files"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from watchdog.events import FileSystemEvent, PatternMatchingEventHandler

from homcc.common.constants import ENCODING
from homcc.common.statefile import StateFile

logger = logging.getLogger(__name__)


@dataclass
class CompilationInfo:
    hostname: str
    phase: str
    filename: str

    def __init__(self, statefile: StateFile):
        self.hostname = statefile.hostname.decode(ENCODING)
        self.phase = StateFile.ClientPhase(statefile.phase).name
        self.filename = statefile.source_base_filename.decode(ENCODING)


class StateFileEventHandler(PatternMatchingEventHandler):
    """tracks state files and adds or removes state files into a list based on their creation or deletion"""

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

            return

        statefile = self.read_statefile(Path(event.src_path))

        if event.event_type == "created":
            if statefile:

                compilation_info = CompilationInfo(statefile)
                self.table_info[event.src_path] = compilation_info

                logger.debug(
                    "Created entry for hostname '%s' in Phase '%s' with source base filename '%s' ",
                    compilation_info.hostname,
                    compilation_info.phase,
                    compilation_info.filename,
                )

                logger.debug(
                    "'%s' - '%s' has been created!", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), event.src_path
                )

            else:
                self.table_info.pop(event.src_path, None)

        elif event.event_type == "modified":
            if statefile:
                if self.table_info.get(event.src_path):
                    self.table_info[event.src_path].phase = StateFile.ClientPhase(statefile.phase).name
                else:
                    self.table_info[event.src_path] = CompilationInfo(statefile)
            else:
                self.table_info.pop(event.src_path, None)

            logger.debug("'%s' - '%s' has been modified!", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), event.src_path)

        elif event.event_type == "deleted":
            self.table_info.pop(event.src_path, None)

            logger.debug("'%s' - '%s' has been deleted!", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), event.src_path)
