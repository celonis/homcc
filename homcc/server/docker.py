# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Logic for the homcc server to interact with docker."""
import logging
import shutil
import subprocess
from typing import List, Optional

from homcc.common.constants import ENCODING
from homcc.common.shell_environment import ShellEnvironment

logger = logging.getLogger(__name__)


def is_docker_available() -> bool:
    """Returns true if docker can be invoked on the server, else False."""
    return shutil.which("docker") is not None


def is_valid_docker_container(docker_container: str) -> bool:
    """Checks whether the specified docker container requested by the client can be used.
    The docker container must exist und run."""
    docker_command = ["docker", "container", "inspect", "-f", "{{.State.Running}}", docker_container]

    try:
        result: subprocess.CompletedProcess = subprocess.run(
            args=docker_command,
            check=True,
            encoding=ENCODING,
            capture_output=True,
            timeout=10,
        )
    except subprocess.CalledProcessError as err:
        if "No such container" in err.stdout:
            logger.warning("Container '%s' is not running, can not compile using this container.", docker_container)
        else:
            logger.error(
                "Error while checking if docker container is running (may indicate it does not exist): %s", err
            )

        return False

    return "true" in result.stdout


class DockerShellEnvironment(ShellEnvironment):
    """Docker shell environment. Commands are transformed to be executed inside a docker container."""

    container: str

    def __init__(self, container: str) -> None:
        super().__init__()
        self.container = container

    def transform_command(self, args: List[str], cwd: Optional[str] = None) -> List[str]:
        transformed_args: List[str] = ["docker", "exec"]

        if cwd is not None:
            transformed_args.extend(["--workdir", cwd])

        transformed_args.append(self.container)
        return transformed_args + args
