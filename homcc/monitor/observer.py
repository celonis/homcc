import logging
from datetime import datetime
from pathlib import Path
from typing import List

from watchdog.events import FileSystemEvent, PatternMatchingEventHandler

from homcc.common.statefile import StateFile
from homcc.monitor.summary import SummaryStats

logger = logging.getLogger(__name__)


class CompilationInfo:
    # extracted from on_created:data_list
    event_src_path: Path
    state_hostname: str
    phase_name: str
    source_base_filename: str


class StateFileObserver(PatternMatchingEventHandler):
    table_info: List[CompilationInfo] = []
    summary: SummaryStats = SummaryStats()

    def on_created(self, event: FileSystemEvent):
        """tracks the creation of a state file and reads its data into table_info"""

        data_list = CompilationInfo()

        try:
            file = Path.read_bytes(Path(event.src_path))
        except FileNotFoundError:
            return

        if len(file) == 0:
            return

        state: StateFile = StateFile.from_bytes(file)

        data_list.event_src_path = event.src_path
        data_list.state_hostname = state.hostname.decode("utf-8")
        data_list.phase_name = StateFile.ClientPhase(state.phase).name
        data_list.source_base_filename = state.source_base_filename  # type: ignore

        self.table_info.append(data_list)

        logger.debug(
            "Created entry for hostname '%s' in Phase '%s' with source base filename '%s' ",
            state.hostname.decode("utf-8"),
            StateFile.ClientPhase(state.phase).name,
            state.source_base_filename,
        )

        time_stamp = datetime.now()
        logger.debug("'%s' - '%s' has been created!", time_stamp.strftime('%d/%m/%Y %H:%M:%S'), event.src_path)

        self.summary.register_compilation(time_stamp, data_list.state_hostname, data_list.source_base_filename)

    def on_deleted(self, event: FileSystemEvent):
        """tracks deletion of a state file - not actively used"""

        for e in self.table_info:
            if e.event_src_path == event.src_path:
                self.table_info.remove(e)

        time_stamp = datetime.now()
        logger.debug("'%s' - '%s' has been deleted!", time_stamp.strftime('%d/%m/%Y %H:%M:%S'), event.src_path)

    @staticmethod
    def on_modified(event: FileSystemEvent):
        """tracks modification of a state file - not actively used"""

        logger.debug("'%s' - '%s' has been modified!", datetime.now().strftime('%d/%m/%Y %H:%M:%S'), event.src_path)

    @staticmethod
    def on_moved(event: FileSystemEvent):
        """tracks path movement of a state file - not actively used"""

        logger.debug("'%s' - '%s' has been moved!", datetime.now().strftime('%d/%m/%Y %H:%M:%S'), event.src_path)
