# Copyright (c) 2023 Celonis SE
# Covered under the included MIT License:
#   https://github.com/celonis/homcc/blob/main/LICENSE

"""Module containing methods to manage the server environment, mostly file and path manipulation."""
import logging
import os
import shutil
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Optional

from homcc.common.arguments import Arguments, ArgumentsExecutionResult
from homcc.common.compression import Compression
from homcc.common.constants import DWARF_FILE_SUFFIX
from homcc.common.messages import CompilationResultMessage, File
from homcc.server.cache import Cache

logger = logging.getLogger(__name__)

COMPILATION_TIMEOUT: float = 240
OBJECT_FILE_SUFFIX = ".o"


class Environment:
    """Represents a server environment."""

    instance_folder: str
    """Path to the current compilation inside /tmp/."""
    mapped_cwd: str
    """Mapped cwd, valid on server side."""
    schroot_profile: Optional[str]
    """schroot profile for the compilation."""
    docker_container: Optional[str]
    """docker container for the compilation."""
    compression: Compression
    """Compression used for data transfer."""
    sock_fd: int
    """File descriptor of the socket that is used to communicate."""

    def __init__(
        self,
        root_folder: Path,
        cwd: str,
        schroot_profile: Optional[str],
        docker_container: Optional[str],
        compression: Compression,
        sock_fd: int,
    ):
        self.instance_folder: str = self.create_instance_folder(root_folder)
        self.mapped_cwd: str = self.map_cwd(cwd, self.instance_folder)
        self.schroot_profile: Optional[str] = schroot_profile
        self.docker_container: Optional[str] = docker_container
        self.compression: Compression = compression
        self.sock_fd: int = sock_fd

    def __del__(self):
        def remove_path(path: Path):
            if path.is_file() or path.is_symlink():
                path.unlink()
                return
            for iter_path in path.iterdir():
                remove_path(iter_path)
            path.rmdir()

        remove_path(Path(self.instance_folder))
        logger.info("Deleted instance folder '%s'.", self.instance_folder)

    @staticmethod
    def link_dependency_to_cache(dependency_file: str, dependency_hash: str, cache: Cache):
        """Links the dependency to a cached dependency with the same hash."""
        # first create the folder structure (if needed), else linking won't work
        dependency_folder = os.path.dirname(dependency_file)
        Path(dependency_folder).mkdir(parents=True, exist_ok=True)

        # then do the actual linking
        os.link(cache.get(dependency_hash), dependency_file)
        logger.debug("Linked '%s' to '%s'.", dependency_file, cache.get(dependency_hash))

    def get_needed_dependencies(self, dependencies: Dict[str, str], cache: Cache) -> Dict[str, str]:
        """Get the dependencies that are not cached and are therefore required to be sent by the client.
        Link cached dependencies so they can be used in the compilation process."""
        needed_dependencies: Dict[str, str] = {}

        for dependency_file, dependency_hash in dependencies.items():
            if dependency_hash in cache:
                self.link_dependency_to_cache(dependency_file, dependency_hash, cache)
            else:
                needed_dependencies[dependency_file] = dependency_hash

        return needed_dependencies

    def map_args(self, arguments: Arguments) -> Arguments:
        """Maps arguments that should be translated (e.g. -I{dir}, .cpp files,
        or the -o argument) to paths valid on the server."""
        return arguments.map(self.instance_folder, self.mapped_cwd)

    @staticmethod
    def create_instance_folder(root_folder: Path) -> str:
        """Creates a folder with random name in the root temp folder. This folder is used for
        storing dependencies and compilation results of a single compilation.
        Returns the path to this folder."""
        instance_folder = os.path.join(root_folder, str(uuid.uuid4()))
        Path(instance_folder).mkdir()

        logger.info("Created dir for new client: %s", instance_folder)

        return instance_folder

    @staticmethod
    def map_cwd(cwd: str, instance_folder: str) -> str:
        """Maps the cwd folder to an absolute path valid on the server."""
        # cwd is an absolute path, to join we have to remove the first /
        return os.path.join(instance_folder, cwd[1:])

    def unmap_path(self, server_path: str) -> str:
        """Unmaps an absolute path from the server to an absolute path valid on the client."""
        return f"/{os.path.relpath(server_path, self.instance_folder)}"

    def map_dependency_paths(self, dependencies: Dict[str, str]) -> Dict[str, str]:
        """Maps dependency paths that the client sent to paths valid at the server."""
        mapped_dependencies = {}
        for path, sha1sum in dependencies.items():
            mapped_path = Arguments.map_path_arg(path, self.instance_folder, self.mapped_cwd)
            mapped_dependencies[mapped_path] = sha1sum

        return mapped_dependencies

    def map_source_file_to_object_file(self, source_file: str, arguments: Arguments) -> Path:
        source_file_path = Path(source_file)

        mapped_path: Path
        if arguments.output is None:
            # When no output is given, the compiler produces the result relative to our working directory.
            mapped_path = Path(self.mapped_cwd) / Path(source_file_path.name).with_suffix(OBJECT_FILE_SUFFIX)
        else:
            output_path = Path(arguments.output)
            mapped_path = output_path.with_suffix(OBJECT_FILE_SUFFIX)

        return mapped_path

    def map_source_file_to_dwarf_file(self, source_file: str, arguments: Arguments) -> Path:
        return self.map_source_file_to_object_file(source_file, arguments).with_suffix(DWARF_FILE_SUFFIX)

    @staticmethod
    def compiler_exists(arguments: Arguments) -> bool:
        """Returns true if the compiler specified in the arguments exists on the system, else false."""
        return shutil.which(str(arguments.compiler)) is not None

    @staticmethod
    def compiler_supports_target(arguments: Arguments, target: str) -> bool:
        """Returns true if the compiler supports cross-compiling for the given target."""
        return arguments.compiler.supports_target(target)

    def do_compilation(self, arguments: Arguments) -> CompilationResultMessage:
        """Does the compilation and returns the filled result message."""
        logger.info("Compiling...")

        mapped_cwd_path = Path(self.mapped_cwd)

        # create the mapped current working directory if it doesn't exist yet
        mapped_cwd_path.mkdir(parents=True, exist_ok=True)

        arguments = arguments.map_symbol_paths(self.instance_folder, "").no_linking()

        if arguments.output is not None:
            Path(arguments.output).parent.mkdir(parents=True, exist_ok=True)

        # relativize the output for the compiler, so that the references to the .o files (e.g. in .dwo files)
        # are also relative instead of absolute
        result = self.invoke_compiler(arguments.relativize_output(mapped_cwd_path))

        object_files: List[File] = []
        dwarf_files: List[File] = []

        def read_and_create_file(path: str) -> File:
            file_content = Path.read_bytes(Path(path))
            client_output_path = self.unmap_path(path)
            return File(client_output_path, bytearray(file_content), self.compression)

        if result.return_code == os.EX_OK:
            for source_file in arguments.source_files:
                object_file_path: str = str(self.map_source_file_to_object_file(source_file, arguments))
                object_file = read_and_create_file(object_file_path)
                object_files.append(object_file)

                if arguments.has_fission() and arguments.is_debug():
                    dwarf_file_path: str = str(self.map_source_file_to_dwarf_file(source_file, arguments))
                    dwarf_file = read_and_create_file(dwarf_file_path)
                    dwarf_files.append(dwarf_file)

                    logger.debug("Found dwarf file: %s", dwarf_file)

                logger.info("Compiled '%s'.", object_file.file_name)

        logger.info(
            "Compiler returned code '%i', sending back #%i object files and #%i dwarf files.",
            result.return_code,
            len(object_files),
            len(dwarf_files),
        )

        return CompilationResultMessage(
            object_files, result.stdout, result.stderr, result.return_code, self.compression, dwarf_files
        )

    def invoke_compiler(self, arguments: Arguments) -> ArgumentsExecutionResult:
        """Actually invokes the compiler process."""
        result: ArgumentsExecutionResult

        if self.schroot_profile is not None:
            result = arguments.schroot_execute(
                profile=self.schroot_profile,
                cwd=self.mapped_cwd,
                timeout=COMPILATION_TIMEOUT,
                event_socket_fd=self.sock_fd,
            )
        elif self.docker_container is not None:
            result = arguments.docker_execute(
                container=self.docker_container,
                cwd=self.mapped_cwd,
                timeout=COMPILATION_TIMEOUT,
                event_socket_fd=self.sock_fd,
            )
        else:
            result = arguments.execute(cwd=self.mapped_cwd, timeout=COMPILATION_TIMEOUT, event_socket_fd=self.sock_fd)

        if result.stdout:
            result.stdout = result.stdout.replace(self.instance_folder, "")
            logger.debug("Compiler gave output:\n'%s'", result.stdout)

        if result.stderr:
            result.stderr = result.stderr.replace(self.instance_folder, "")
            logger.warning("Compiler gave error output %s:\n'%s'", self.instance_folder, result.stderr)

        return result


def create_root_temp_folder() -> TemporaryDirectory:
    """Creates and returns the root folder of homcc inside /tmp."""
    return TemporaryDirectory(prefix="homcc_")
