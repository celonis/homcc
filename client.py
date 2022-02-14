#!/usr/bin/env python3
"""
homcc client
"""

import os
import sys

from homcc.client import *
from homcc.messages import ArgumentMessage
from typing import Dict, List

log: logging.Logger = logging.getLogger(__name__)


async def main() -> int:
    """ client main function for parsing arguments and communicating with the homcc server """
    args: List[str] = sys.argv[1:]  # caller arguments
    cwd: str = os.getcwd()  # current working directory

    host: str = "localhost"
    port: int = 3633

    # timeout windows in seconds for sending and receiving messages
    timeout_send: int = 30
    timeout_recv: int = 180

    client: TCPClient = TCPClient(host, port)

    try:
        # 1.) find dependencies
        dependency_list: List[str] = get_dependencies(args)
        log.debug(dependency_list)

        # 2.) try to connect with server
        await client.connect()

        # 3.) parse cmd-line args and get dependencies
        dependency_hashes: Dict[str, str] = calculate_dependency_hashes(cwd, dependency_list)
        log.debug(dependency_hashes)

        # 4.) send argument message to server
        argument_message: ArgumentMessage = ArgumentMessage(args, cwd, dependency_hashes)
        await client.send(argument_message, timeout_send)

        # 4.a) handle timed out messages
        for _ in await client.get_timed_out_messages():
            pass  # TODO(s.pirsch): compile locally instead

        # 5.) receive server response
        _ = await client.receive(timeout=timeout_recv)

        # 6.) send missing dependencies

        # 7.) receive compilation results from server

        # 8.) disconnect from server
        await client.close()

    except subprocess.CalledProcessError as err:
        log.warning("Error during dependency search:\n%s", err.stderr.decode(encoding))
        return err.returncode

    except ConnectionError as err:
        log.warning("Failed to establish connection to %s:%i:\t%s", host, port, err)
        # TODO(s.pirsch): compile locally instead
        return err.errno

    return os.EX_OK


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
