"""Module containing methods to manage the server environment, mostly file and path manipulation."""
from dataclasses import dataclass
from threading import Lock
import uuid
import os
import subprocess
import logging
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Dict, List

from homcc.common.arguments import Arguments
from homcc.common.compression import Compression
from homcc.common.messages import CompilationResultMessage, ObjectFile

logger = logging.getLogger(__name__)


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


def symlink_dependency_to_cache(dependency_file: str, dependency_hash: str, cache: Dict[str, str], cache_mutex: Lock):
    """Symlinks the dependency to a cached dependency with the same hash."""
    # first create the folder structure (if needed), else symlinking won't work
    dependency_folder = os.path.dirname(dependency_file)
    Path(dependency_folder).mkdir(parents=True, exist_ok=True)

    # then do the actual symlinking
    with cache_mutex:
        os.symlink(cache[dependency_hash], dependency_file)
        logger.debug("Symlinked '%s' to '%s'.", dependency_file, cache[dependency_hash])


def get_needed_dependencies(dependencies: Dict[str, str], cache: Dict[str, str], cache_mutex: Lock) -> Dict[str, str]:
    """Get the dependencies that are not cached and are therefore required to be sent by the client.
    Symlink cached dependencies so they can be used in the compilation process."""
    needed_dependencies: Dict[str, str] = {}

    for dependency_file, dependency_hash in dependencies.items():
        with cache_mutex:
            is_cached = dependency_hash in cache

        if is_cached:
            symlink_dependency_to_cache(dependency_file, dependency_hash, cache, cache_mutex)
        else:
            needed_dependencies[dependency_file] = dependency_hash

    return needed_dependencies


def map_arguments(instance_path: str, mapped_cwd: str, arguments: List[str]) -> List[str]:
    """Maps arguments that should be translated (e.g. -I{dir}, .cpp files,
    or the -o argument) to paths valid on the server."""
    return list(Arguments.from_args(arguments).map(instance_path, mapped_cwd))


def unmap_path(instance_path: str, server_path: str) -> str:
    """Unmaps an absolute path from the server to an absolute path valid on the client."""
    return f"/{os.path.relpath(server_path, instance_path)}"


def map_dependency_paths(instance_path: str, mapped_cwd: str, dependencies: Dict[str, str]) -> Dict[str, str]:
    """Maps dependency paths that the client sent to paths valid at the server."""
    mapped_dependencies = {}
    for path, sha1sum in dependencies.items():
        mapped_path = Arguments.map_path_arg(path, instance_path, mapped_cwd)
        mapped_dependencies[mapped_path] = sha1sum

    return mapped_dependencies


def map_source_file_to_object_file(mapped_cwd: str, source_file: str) -> str:
    return os.path.join(mapped_cwd, f"{Path(source_file).stem}.o")


@dataclass
class CompilerResult:
    """Information that the compiler process gives after executing."""

    return_code: int
    stdout: str
    stderr: str


def invoke_compiler(mapped_cwd: str, arguments: List[str]) -> CompilerResult:
    """Actually invokes the compiler process."""
    logger.debug("Compile arguments: %s", arguments)

    # pylint: disable=subprocess-run-check
    # (justification: we explicitly return the result code)
    result = subprocess.run(
        arguments,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=mapped_cwd,
    )

    stdout = ""
    if result.stdout:
        stdout = result.stdout.decode("utf-8")
        logger.debug("Compiler gave output:\n'%s'", stdout)

    stderr = ""
    if result.stderr:
        stderr = result.stderr.decode("utf-8")
        logger.warning("Compiler gave error output:\n'%s'", stderr)

    return CompilerResult(result.returncode, stdout, stderr)


def do_compilation(
    instance_path: str, mapped_cwd: str, args: List[str], compression: Compression
) -> CompilationResultMessage:
    """Does the compilation and returns the filled result message."""
    logger.info("Compiling...")

    # create the mapped current working directory if it doesn't exist yet
    Path(mapped_cwd).mkdir(parents=True, exist_ok=True)

    arguments: Arguments = Arguments.from_args(args).no_linking()

    result = invoke_compiler(mapped_cwd, list(arguments))

    object_files: List[ObjectFile] = []
    if result.return_code == 0:
        for source_file in arguments.source_files:
            object_file_path: str = map_source_file_to_object_file(mapped_cwd, source_file)
            object_file_content = Path.read_bytes(Path(object_file_path))

            client_output_path = unmap_path(instance_path, object_file_path)

            object_file = ObjectFile(client_output_path, bytearray(object_file_content), compression)
            object_files.append(object_file)

            logger.info("Compiled '%s'.", object_file.file_name)

    logger.info(
        "Compiler returned code '%i', sending back #%i object files.",
        result.return_code,
        len(object_files),
    )
    return CompilationResultMessage(object_files, result.stdout, result.stderr, result.return_code, compression)
