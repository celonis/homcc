#!/usr/bin/env python3
"""
homcc client
"""
import asyncio
import logging
import sys
import os

from pathlib import Path
from typing import Dict, List, Set

from homcc.client.client import TCPClient, TCPClientError
from homcc.client.client_utils import CompilerError, calculate_dependency_dict, find_dependencies, local_compile
from homcc.messages import Message, MessageType, ObjectFile


async def main() -> int:
    """client main function for parsing arguments and communicating with the homcc server"""
    args: List[str] = sys.argv  # caller arguments
    compiler: str = "g++"  # supported C/C++ compilers: [gcc, g++, clang, clang++]
    cwd: str = os.getcwd()  # current working directory

    host: str = "localhost"
    port: int = 3633

    # timeout window in seconds for receiving messages
    timeout: int = 1

    client: TCPClient = TCPClient(host, port)

    # overwrite homcc call with specified compiler
    args[0] = compiler

    try:
        # 1.) find dependencies
        dependencies: Set[str] = find_dependencies(args)
        logger.debug("Dependency list: %s", dependencies)

        # 2.) try to connect with server
        await client.connect()

        # 3.) parse cmd-line arguments and calculate file hashes of given dependencies
        dependency_dict: Dict[str, str] = calculate_dependency_dict(dependencies)
        logger.debug("Dependency hashes: %s", dependency_dict)

        # 4.) send argument message to server
        await client.send_argument_message(args, cwd, dependency_dict)

        # 5.) provide requested, missing dependencies
        server_response: Message = await client.receive(timeout=timeout)

        while server_response.message_type == MessageType.DependencyRequestMessage:
            requested_dependency: str = dependency_dict[server_response.get_sha1sum()]
            await client.send_dependency_reply_message(requested_dependency)

            server_response = await client.receive(timeout=timeout)

        # 6.) compilation result expected
        if not server_response.message_type == MessageType.CompilationResultMessage:
            logger.error("Unexpected message of type %s received!", str(server_response.message_type))
            raise TCPClientError

        object_files: List[ObjectFile] = server_response.get_object_files()

        for object_file in object_files:
            Path(object_file.file_name).write_bytes(object_file.content)

        # 7.) gracefully disconnect from server
        await client.close()

        return os.EX_OK

    # unrecoverable errors
    except CompilerError as err:
        return err.returncode

    # recoverable errors by compiling locally instead
    except TCPClientError:
        return local_compile(args)


if __name__ == "__main__":
    # TODO(s.pirsch): make logging level configurable via caller or config file
    logging.basicConfig(level=logging.DEBUG)
    logger: logging.Logger = logging.getLogger(__name__)
    sys.exit(asyncio.run(main()))
