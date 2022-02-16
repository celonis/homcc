import uuid
import os
import subprocess
import logging
from pathlib import Path
from typing import Dict, List

from homcc.messages import ObjectFile

logger = logging.getLogger(__name__)


def create_instance_folder() -> str:
    """Creates a folder with random name in /tmp/homcc.
    This folder is used for storing dependencies and
    compilation results of a single compilation."""
    path = f"/tmp/homcc/{uuid.uuid4()}/"
    Path(path).mkdir(parents=True, exist_ok=True)

    return path


def map_cwd(instance_folder: str, cwd: str) -> str:
    """Maps the cwd folder to an absolute path valid on the server."""
    # cwd is an absolute path, to join we have to remove the first /
    return os.path.join(instance_folder, cwd[1:])


def save_dependency(absolute_dependency_path: str, content: bytearray):
    """Writes the dependency to disk."""
    os.makedirs(os.path.dirname(absolute_dependency_path), exist_ok=True)
    dependency_file = open(absolute_dependency_path, "wb")
    dependency_file.write(content)

    logger.debug(f"Wrote file {absolute_dependency_path}")


def get_needed_dependencies(dependencies: Dict[str, str]) -> Dict[str, str]:
    """Get the dependencies that are not cached and are
    therefore required to be sent by the client."""
    # TODO: Check here if dependency is already in cache. For now we assume we have no cache.
    return dependencies.copy()


def map_arguments(
    instance_path: str, mapped_cwd: str, arguments: List[str]
) -> List[str]:
    """Maps include and src arguments (e.g. -I{dir} or the to be compiled .cpp files)
    to paths valid on the server."""
    mapped_arguments = [arguments[0]]

    include_prefixes = ["-I"]
    for argument in arguments[1:]:
        if argument.startswith("-"):
            for include_prefix in include_prefixes:
                if argument.startswith(include_prefix):
                    include_path = argument[len(include_prefix) :]
                    mapped_include_path = _map_path(
                        instance_path, mapped_cwd, include_path
                    )
                    argument = include_prefix + mapped_include_path
        else:
            argument = _map_path(instance_path, mapped_cwd, argument)

        mapped_arguments.append(argument)

    return mapped_arguments


def _map_path(instance_path: str, mapped_cwd: str, path: str) -> str:
    """Maps absolute or relative path from client to
    absolute path on the server."""
    if os.path.isabs(path):
        # in case of an absolute path we have to remove the first /
        # (else os.path.join ignores the paths previous to this)
        return os.path.join(instance_path, path[1:])
    else:
        return os.path.join(mapped_cwd, path)


def map_dependency_paths(
    instance_path: str, mapped_cwd: str, dependencies: Dict[str, str]
) -> Dict[str, str]:
    """Maps dependency paths that the client sent to paths valid at the server."""
    mapped_dependencies = {}
    for path, sha1sum in dependencies.items():
        mapped_path = _map_path(instance_path, mapped_cwd, path)
        mapped_dependencies[mapped_path] = sha1sum

    return mapped_dependencies


def extract_source_files(arguments: List[str]) -> List[str]:
    """Given arguments, extracts files to be compiled and returns their paths."""
    source_file_paths: List[str] = []

    # only consider real arguments (not the compiler, hence arguments[1:])
    for argument in arguments[1:]:
        if not argument.startswith("-"):
            source_file_paths.append(argument)

    return source_file_paths


def compile(mapped_cwd: str, arguments: List[str]) -> List[ObjectFile]:
    logger.info("Compiling...")

    # -c says that we do not want to link
    arguments.insert(1, "-c")

    logger.debug(f"Compile arguments: {arguments}")

    compiler_process = subprocess.Popen(
        arguments,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=mapped_cwd,
    )

    stdout_bytes, stderr_bytes = compiler_process.communicate()

    stdout = stdout_bytes.decode("utf-8")
    if stdout:
        logger.debug(f"Compiler gave output:\n {stdout}")

    stderr = stderr_bytes.decode("utf-8")
    if stderr:
        logger.error(f"Compiler gave error output:\n {stderr}")

    results: List[ObjectFile] = []
    source_files: List[str] = extract_source_files(arguments)

    for source_file in source_files:
        file_name = f"{Path(source_file).stem}.o"
        object_file_content = open(os.path.join(mapped_cwd, file_name), "rb")

        object_file = ObjectFile(source_file, bytearray(object_file_content.read()))
        results.append(object_file)

    logger.info(f"Sending back #{len(results)} object files to the client.")

    return results
