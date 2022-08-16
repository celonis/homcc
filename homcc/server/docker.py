"""Logic for the homcc server to interact with docker."""
import logging
import shutil
import subprocess

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
            encoding="utf-8",
            capture_output=True,
            timeout=10,
        )
    except subprocess.CalledProcessError as err:
        if "No such container" in err.stdout:
            logger.warning("Container '%s' is not running, can not compile using this container.", docker_container)
        else:
            logger.error("Could not check if container is running: %s", err)

        return False

    return "true" in result.stdout
