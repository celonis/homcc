"""Module containing methods to manage the server environment, mostly file and path manipulation."""
import uuid
import os
import subprocess
import logging
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Dict, List

from homcc.messages import ObjectFile

logger = logging.getLogger(__name__)
_include_prefixes = ["-I", "-isysroot", "-isystem"]


def create_root_temp_folder() -> TemporaryDirectory:
    """Creates and returns the root folder of homcc inside /tmp."""
    return TemporaryDirectory(prefix="homcc_")


def create_instance_folder(root_temp_folder: str) -> str:
    """Creates a folder with random name in the root temp folder.
    This folder is used for storing dependencies and
    compilation results of a single compilation.
    Returns the path to this folder."""
    instance_folder = os.path.join(root_temp_folder, str(uuid.uuid4()))
    Path(instance_folder).mkdir()

    return instance_folder


def map_cwd(instance_folder: str, cwd: str) -> str:
    """Maps the cwd folder to an absolute path valid on the server."""
    # cwd is an absolute path, to join we have to remove the first /
    return os.path.join(instance_folder, cwd[1:])


def save_dependency(absolute_dependency_path: str, content: bytearray):
    """Writes the dependency to disk."""
    os.makedirs(os.path.dirname(absolute_dependency_path), exist_ok=True)
    Path.write_bytes(Path(absolute_dependency_path), content)

    logger.debug("Wrote file %s", absolute_dependency_path)


def get_needed_dependencies(dependencies: Dict[str, str]) -> Dict[str, str]:
    """Get the dependencies that are not cached and are
    therefore required to be sent by the client."""
    # TODO: Check here if dependency is already in cache. For now we assume we have no cache.
    return dependencies.copy()


def map_arguments(instance_path: str, mapped_cwd: str, arguments: List[str]) -> List[str]:
    """Maps include and src arguments (e.g. -I{dir} or the to be compiled .cpp files)
    to paths valid on the server."""
    mapped_arguments = [arguments[0]]

    open_include_prefix = False
    open_prefix = False
    for argument in arguments[1:]:
        if argument.startswith("-"):
            open_prefix = True
            for include_prefix in _include_prefixes:
                if argument.startswith(include_prefix) and argument != include_prefix:
                    open_include_prefix = True

                    include_path = argument[len(include_prefix) :]
                    mapped_include_path = _map_path(instance_path, mapped_cwd, include_path)
                    argument = include_prefix + mapped_include_path
        elif open_include_prefix or not open_prefix:
            # 'open_include_prefix': must be include argument, translate include argument paths
            # not 'open_prefix': must be 'infile' argument (source files), also translate paths
            argument = _map_path(instance_path, mapped_cwd, argument)
            open_include_prefix = False
            open_prefix = False
        else:
            open_prefix = False

        mapped_arguments.append(argument)

    return mapped_arguments


def _map_path(instance_path: str, mapped_cwd: str, path: str) -> str:
    """Maps absolute or relative path from client to
    absolute path on the server."""
    joined_path: str
    if os.path.isabs(path):
        # in case of an absolute path we have to remove the first /
        # (else os.path.join ignores the paths previous to this)
        joined_path = os.path.join(instance_path, path[1:])
    else:
        joined_path = os.path.join(mapped_cwd, path)

    # remove any '..' or '.' inside paths
    return os.path.realpath(joined_path)


def map_dependency_paths(instance_path: str, mapped_cwd: str, dependencies: Dict[str, str]) -> Dict[str, str]:
    """Maps dependency paths that the client sent to paths valid at the server."""
    mapped_dependencies = {}
    for sha1sum, path in dependencies.items():
        mapped_path = _map_path(instance_path, mapped_cwd, path)
        mapped_dependencies[sha1sum] = mapped_path

    return mapped_dependencies


def extract_source_files(arguments: List[str]) -> List[str]:
    """Given arguments, extracts files to be compiled and returns their paths."""
    source_file_paths: List[str] = []

    open_include_arguments = False
    # only consider real arguments (not the compiler, hence arguments[1:])
    for argument in arguments[1:]:
        if argument.startswith("-"):
            for include_prefix in _include_prefixes:
                if argument == include_prefix:
                    open_include_arguments = True
                    break

            if open_include_arguments:
                continue
        else:
            if not open_include_arguments:
                source_file_paths.append(argument)

        open_include_arguments = False

    return source_file_paths


def do_compilation(mapped_cwd: str, arguments: List[str]) -> List[ObjectFile]:
    logger.info("Compiling...")

    # -c says that we do not want to link
    arguments.insert(1, "-c")

    logger.debug("Compile arguments: %s", arguments)

    # pylint: disable=subprocess-run-check
    # (justification: we explicitly return the result code)
    result = subprocess.run(
        arguments,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=mapped_cwd,
    )

    if result.stdout:
        stdout = result.stdout.decode("utf-8")
        logger.debug("Compiler gave output:\n%s", stdout)

    if result.stderr:
        stderr = result.stderr.decode("utf-8")
        logger.error("Compiler gave error output:\n%s", stderr)

    results: List[ObjectFile] = []
    source_files: List[str] = extract_source_files(arguments)

    for source_file in source_files:
        file_name = f"{Path(source_file).stem}.o"
        object_file_content = Path.read_bytes(Path(os.path.join(mapped_cwd, file_name)))

        object_file = ObjectFile(source_file, bytearray(object_file_content))
        results.append(object_file)

    logger.info("Sending back #%i object files to the client.", len(results))

    return results
