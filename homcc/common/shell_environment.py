"""Shell environment module."""

from abc import ABC, abstractmethod
from typing import List, Optional


class ShellEnvironment(ABC):
    """Abstract class representing a shell environment. A shell environment defines
    the shell in which commands are executed, e.g. inside a container or directly
    on the host system."""

    @abstractmethod
    def transform_command(self, args: List[str], cwd: Optional[str] = None) -> List[str]:
        pass


class HostShellEnvironment(ShellEnvironment):
    """Host shell environment. Commands are not transformed."""

    def transform_command(self, args: List[str], cwd: Optional[str] = None) -> List[str]:
        return args
