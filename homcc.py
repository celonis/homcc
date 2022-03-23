#!/usr/bin/env python3
"""
homcc client
"""
import asyncio
import logging
import sys
import os

from pathlib import Path
from typing import Dict, Set

from homcc.common.arguments import Arguments, ArgumentsExecutionResult
from homcc.client.client import TCPClient, TCPClientError, UnexpectedMessageTypeError
from homcc.client.client_utils import (
    CompilerError,
    calculate_dependency_dict,
    find_dependencies,
    local_compile,
    link_object_files
)
from homcc.common.messages import Message, CompilationResultMessage, DependencyRequestMessage


async def main() -> int:
    """ client main function for parsing arguments and communicating with the homcc server """
    arguments: Arguments = Arguments(sys.argv)  # caller arguments
    compiler: str = "g++"  # supported C/C++ compilers: [gcc, g++, clang, clang++]
    cwd: str = os.getcwd()  # current working directory

    host: str = "localhost"
    port: int = 3633

    # timeout window in seconds for receiving messages
    timeout: int = 1

    client: TCPClient = TCPClient(host, port)

    # overwrite homcc call with specified compiler
    arguments.compiler = compiler

    try:
        # 1.) test whether arguments should be sent, prepare for communication with server
        if not arguments.is_sendable():
            return local_compile(arguments)

        dependencies: Set[str] = find_dependencies(arguments)
        logger.debug("Dependency list: %s", dependencies)
        dependency_dict: Dict[str, str] = calculate_dependency_dict(dependencies)
        logger.debug("Dependency hashes: %s", dependency_dict)

        await client.connect()

        # 2.) send arguments and dependency information to server and provide requested dependencies
        await client.send_argument_message(arguments, cwd, dependency_dict)

        server_response: Message = await client.receive(timeout=timeout)

        while isinstance(server_response, DependencyRequestMessage):
            requested_dependency: str = dependency_dict[server_response.get_sha1sum()]
            await client.send_dependency_reply_message(requested_dependency)

            server_response = await client.receive(timeout=timeout)

        # 3.) receive final message and close client
        if not isinstance(server_response, CompilationResultMessage):
            logger.error("Unexpected message of type %s received!", server_response.message_type)
            raise UnexpectedMessageTypeError

        await client.close()

        # 4.) extract compilation results
        server_result: ArgumentsExecutionResult = server_response.get_compilation_result()

        if server_result.stdout:
            logger.debug("Server output:\n%s", server_result.stdout)

        if server_result.return_code != os.EX_OK:
            logger.warning("Server error(%i):\n%s", server_result.return_code, server_result.stderr)

            # for now, we try to recover from server compilation errors via local compilation to track bugs
            return_code: int = local_compile(arguments)

            if return_code != server_result.return_code:
                logger.debug("Different compilation result errors: Client error(%i) - Server error(%i)",
                             return_code, server_result.return_code)

            return return_code

        for object_file in server_response.get_object_files():
            Path(object_file.file_name).write_bytes(object_file.content)

        # 5.) link and delete object files if required
        if arguments.is_linking():
            return_code: int = link_object_files(arguments)

            for object_file in server_response.get_object_files():
                Path(object_file.file_name).unlink()

            return return_code

        return os.EX_OK

    # unrecoverable errors
    except CompilerError as err:
        return err.returncode

    # recoverable errors
    except TCPClientError:
        return local_compile(arguments)


if __name__ == '__main__':
    # TODO(s.pirsch): make logging level configurable via caller or config file
    logging.basicConfig(level=logging.DEBUG)
    logger: logging.Logger = logging.getLogger(__name__)
    sys.exit(asyncio.run(main()))
