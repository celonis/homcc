"""Module containing methods to manage the server environment, mostly file and path manipulation."""
from tempfile import TemporaryDirectory
import uuid
import os
import shutil
import logging
from pathlib import Path
from typing import Dict, List, Optional

from homcc.common.arguments import Arguments, ArgumentsExecutionResult
from homcc.common.compression import Compression
from homcc.common.messages import CompilationResultMessage, ObjectFile
from homcc.server.cache import Cache

logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        root_folder: Path,
        cwd: str,
        schroot_profile: Optional[str],
        docker_container: Optional[str],
        compression: Compression,
    ):
        self.instance_folder: str = self.create_instance_folder(root_folder)
        self.mapped_cwd: str = self.map_cwd(cwd, self.instance_folder)
        self.schroot_profile: Optional[str] = schroot_profile
        self.docker_container: Optional[str] = docker_container
        self.compression: Compression = compression

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

    def map_args(self, args: List[str]) -> Arguments:
        """Maps arguments that should be translated (e.g. -I{dir}, .cpp files,
        or the -o argument) to paths valid on the server."""
        return Arguments.from_args(args).map(self.instance_folder, self.mapped_cwd)

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

    def map_source_file_to_object_file(self, source_file: str) -> str:
        return os.path.join(self.mapped_cwd, f"{Path(source_file).stem}.o")

    @staticmethod
    def compiler_exists(arguments: Arguments) -> bool:
        """Returns true if the compiler specified in the arguments exists on the system, else false."""
        compiler = arguments.compiler
        return compiler is not None and shutil.which(compiler) is not None

    def do_compilation(self, arguments: Arguments) -> CompilationResultMessage:
        """Does the compilation and returns the filled result message."""
        logger.info("Compiling...")

        # create the mapped current working directory if it doesn't exist yet
        Path(self.mapped_cwd).mkdir(parents=True, exist_ok=True)

        result = self.invoke_compiler(arguments.no_linking())

        object_files: List[ObjectFile] = []
        if result.return_code == os.EX_OK:
            for source_file in arguments.source_files:
                object_file_path: str = self.map_source_file_to_object_file(source_file)
                object_file_content = Path.read_bytes(Path(object_file_path))

                client_output_path = self.unmap_path(object_file_path)

                object_file = ObjectFile(client_output_path, bytearray(object_file_content), self.compression)
                object_files.append(object_file)
                logger.info("Compiled '%s'.", object_file.file_name)

        logger.info(
            "Compiler returned code '%i', sending back #%i object files.",
            result.return_code,
            len(object_files),
        )

        return CompilationResultMessage(
            object_files,
            result.stdout,
            result.stderr,
            result.return_code,
            self.compression,
        )

    def invoke_compiler(self, arguments: Arguments) -> ArgumentsExecutionResult:
        """Actually invokes the compiler process."""
        result: ArgumentsExecutionResult

        if self.schroot_profile is not None:
            result = arguments.schroot_execute(profile=self.schroot_profile, cwd=self.mapped_cwd)
        elif self.docker_container is not None:
            result = arguments.docker_execute(container=self.docker_container, cwd=self.mapped_cwd)
        else:
            result = arguments.execute(cwd=self.mapped_cwd)

        if result.stdout:
            logger.debug("Compiler gave output:\n'%s'", result.stdout)

        if result.stderr:
            logger.warning("Compiler gave error output %s:\n'%s'", self.instance_folder, result.stderr)

        return result


def create_root_temp_folder() -> TemporaryDirectory:
    """Creates and returns the root folder of homcc inside /tmp."""
    return TemporaryDirectory(prefix="homcc_")
