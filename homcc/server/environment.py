"""Module containing methods to manage the server environment, mostly file and path manipulation."""
from dataclasses import dataclass
import uuid
import os
import subprocess
import logging
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Dict, List, Optional

from homcc.common.arguments import Arguments
from homcc.common.messages import CompilationResultMessage, ObjectFile

logger = logging.getLogger(__name__)

# arguments of which the path should be translated
_path_argument_prefixes = ["-I", "-isysroot", "-isystem", "-o"]


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
    """Maps arguments that should be translated (e.g. -I{dir}, .cpp files,
    or the -o argument) to paths valid on the server."""
    mapped_arguments = [arguments[0]]

    open_path_argument_prefix = False
    open_prefix = False
    for argument in arguments[1:]:
        if argument.startswith("-"):
            open_prefix = True
            for path_argument_prefix in _path_argument_prefixes:
                if argument.startswith(path_argument_prefix):
                    open_path_argument_prefix = True

                    if argument == path_argument_prefix:
                        break
                    else:
                        argument_path = argument[len(path_argument_prefix) :]
                        mapped_path = _map_path(instance_path, mapped_cwd, argument_path)
                        argument = path_argument_prefix + mapped_path
        elif open_path_argument_prefix or not open_prefix:
            # 'open_path_argument_prefix': must be an argument which requires path translation
            # not 'open_prefix': must be 'infile' argument (source files), also translate paths
            argument = _map_path(instance_path, mapped_cwd, argument)
            open_path_argument_prefix = False
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


def _unmap_path(instance_path: str, server_path: str) -> str:
    """Unmaps an absolute path from the server to an absolute path valid on the client."""
    return f"/{os.path.relpath(server_path, instance_path)}"


def map_dependency_paths(instance_path: str, mapped_cwd: str, dependencies: Dict[str, str]) -> Dict[str, str]:
    """Maps dependency paths that the client sent to paths valid at the server."""
    mapped_dependencies = {}
    for sha1sum, path in dependencies.items():
        mapped_path = _map_path(instance_path, mapped_cwd, path)
        mapped_dependencies[sha1sum] = mapped_path

    return mapped_dependencies


def map_source_file_to_object_file(mapped_cwd: str, source_file: str) -> str:
    return os.path.join(mapped_cwd, f"{Path(source_file).stem}.o")


def get_output_path(mapped_cwd: str, source_file_name: str, arguments: List[str]) -> str:
    """Extracts the output path (-o argument) from the argument list.
    If there is no output argument given by the user, returns the default output path."""
    output_path = os.path.join(mapped_cwd, f"{Path(source_file_name).stem}.o")

    for index, argument in enumerate(arguments):
        if argument.startswith("-o"):
            if argument == "-o":
                output_path = arguments[index + 1]
            else:
                output_path = argument[2:]

            break

    return output_path


@dataclass
class CompilerResult:
    """Information that the compiler process gives after executing."""

    return_code: int
    stdout: str
    stderr: str


def invoke_compiler(mapped_cwd: str, arguments: List[str]) -> CompilerResult:
    """Actually invokes the compiler process."""
    logger.info("Compile arguments: %s", arguments)

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


def do_compilation(instance_path: str, mapped_cwd: str, args: List[str]) -> CompilationResultMessage:
    """Does the compilation and returns the filled result message."""
    logger.info("Compiling...")

    # create the mapped current working directory if it doesn't exist yet
    Path(mapped_cwd).mkdir(parents=True, exist_ok=True)

    arguments: Arguments = Arguments(args).no_linking()
    source_files: List[str] = arguments.source_files

    result = invoke_compiler(mapped_cwd, list(arguments))

    object_files: List[ObjectFile] = []
    if result.return_code == 0:
        for source_file in source_files:
            object_file_path: str = map_source_file_to_object_file(mapped_cwd, source_file)
            object_file_content = Path.read_bytes(Path(object_file_path))

            client_output_path = _unmap_path(instance_path, object_file_path)

            object_file = ObjectFile(client_output_path, bytearray(object_file_content))
            object_files.append(object_file)

    logger.info(
        "Compiler returned code '%i', sending back #%i object files.",
        result.return_code,
        len(object_files),
    )
    return CompilationResultMessage(object_files, result.stdout, result.stderr, result.return_code)
