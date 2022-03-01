#!/usr/bin/env python3
"""
homcc client
"""
import asyncio
import logging
import sys
import os

from typing import Dict, List, Set

from homcc.client.client import TCPClient, TCPClientError
from homcc.client.client_utils import (
    CompilerError,
    calculate_dependency_hashes,
    find_dependencies,
    local_compile
)
from homcc.messages import (
    Message,
    DependencyRequestMessage,
    MessageType
)


async def main() -> int:
    """ client main function for parsing arguments and communicating with the homcc server """
    args: List[str] = sys.argv  # caller arguments
    compiler: str = "g++"  # supported C/C++ compilers: [gcc, g++, clang, clang++]
    cwd: str = os.getcwd()  # current working directory

    host: str = "localhost"
    port: int = 3633

    # timeout windows in seconds for sending and receiving messages
    timeout_send: int = 30
    timeout_recv: int = 180

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
        dependency_hashes: Dict[str, str] = calculate_dependency_hashes(cwd, dependencies)
        logger.debug("Dependency hashes: %s", dependency_hashes)

        # 4.) send argument message to server
        await client.send_argument_message(args, cwd, dependency_hashes, timeout_send)

        # 5.) provide requested, missing dependencies
        server_response: Message = await client.receive(timeout=timeout_recv)

        while server_response.message_type == MessageType.DependencyRequestMessage:
            # 5.1) receive request for missing dependency
            dependency_request: DependencyRequestMessage = DependencyRequestMessage.from_dict(
                server_response._get_json_dict())

            # 5.2) respond with missing dependency
            dependency_file_name: str = dependency_hashes[dependency_request.get_sha1sum()]
            dependency_file_path: str = f"{cwd}/{dependency_file_name}"

            await client.send_dependency_reply_message(dependency_file_path, timeout=timeout_send)

            server_response = await client.receive(timeout=timeout_recv)

        # 6.) receive compilation result from server
        # TODO(s.pirsch): receive CompilationResultMessage
        # if server_response.message_type == MessageType.CompilationResultMessage:
        # _ = await client.receive(timeout=timeout_recv)

        # 7.) gracefully disconnect from server
        await client.close()

        return os.EX_OK

    # unrecoverable errors
    except CompilerError as err:
        return err.returncode

    # recoverable errors by compiling locally instead
    except TCPClientError:
        return local_compile(args)


if __name__ == '__main__':
    # TODO(s.pirsch): make logging level configurable via caller or config file
    logging.basicConfig(level=logging.DEBUG)
    logger: logging.Logger = logging.getLogger(__name__)
    sys.exit(asyncio.run(main()))
