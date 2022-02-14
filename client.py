#!/usr/bin/env python3
"""
TODO: Client execution entry point
"""
import hashlib
import os
import subprocess
import sys

from typing import Dict, List
from homcc.client import *
from homcc.messages import ArgumentMessage

log: logging.Logger = logging.getLogger(__name__)
encoding: str = "utf-8"


def get_dependencies(cmd: List[str]) -> List[str]:
    """ get list of dependencies by calling the preprocessor """
    # count and specify preprocessor targets, usually only one
    target_count: int = 0

    for i, arg in enumerate(cmd):
        if arg == "-o":
            target_count += 1
            cmd[i] = "-MT"

    # specify compiler
    cmd.insert(0, "g++")

    # add option to get dependencies without system headers
    cmd.insert(1, "-MM")

    # execute command, e.g.: "g++ -MM foo.cpp -MT bar.o"
    result: subprocess.CompletedProcess = subprocess.run(cmd, check=True,
                                                         stdout=subprocess.PIPE,
                                                         stderr=subprocess.PIPE)
    # ignore target file(s) and line break characters
    dependency_list: List[str] = list(filter(lambda dependency: dependency != "\\",
                                             result.stdout.decode(encoding)
                                             .split()[target_count:]))
    return dependency_list


def calculate_dependency_hashes(cwd: str, dependency_list: List[str]) -> Dict[str, str]:
    """ calculate dependency file hashes """

    def hash_file(filepath: str) -> str:
        with open(filepath, mode="rb") as file:
            return hashlib.sha1(file.read()).hexdigest()

    return {filename: hash_file(f"{cwd}/{filename}") for filename in dependency_list}


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
        print(argument_message.get_json_str())
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
        log.warning("Error during dependency search:\n%s",
                    err.stderr.decode(encoding))
        return err.returncode
    except ConnectionError as err:
        log.warning("Failed to establish connection to %s:%i:\t%s", host, port, err)
        return err.errno
        # TODO(s.pirsch): log.warning("Compiling locally instead!")

    return os.EX_OK


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
