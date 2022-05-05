""" Tests for client/client.py"""

from typing import Dict, Iterator, List, Set

import pytest

from homcc.common.arguments import Arguments
from homcc.client.client import HostSelector, TCPClient
from homcc.client.compilation import calculate_dependency_dict, find_dependencies
from homcc.client.errors import HostsExhaustedError
from homcc.client.parsing import ConnectionType, Host, parse_host
from homcc.server.server import start_server, stop_server


class TestHostSelector:
    """Tests for HostSelector"""

    # first host will be ignored by the host selector due to 0 limit
    HOSTS: List[str] = ["remotehost0/0", "remotehost1/1", "remotehost2/2", "remotehost3/4", "remotehost4/8"]
    PARSED_HOSTS: List[Host] = [parse_host(host) for host in HOSTS]

    def test_host_selector(self):
        host_selector: HostSelector = HostSelector(self.HOSTS)

        host_iter: Iterator = iter(host_selector)
        for count, host in enumerate(host_iter):
            assert host in self.PARSED_HOSTS
            assert count == len(self.HOSTS[1:]) - len(host_selector) - 1

        assert len(host_selector) == 0
        with pytest.raises(StopIteration):
            assert next(host_iter)

    def test_host_selector_with_tries(self):
        host_selector: HostSelector = HostSelector(self.HOSTS, 3)

        host_iter: Iterator = iter(host_selector)
        for _ in range(3):
            host: Host = next(host_iter)
            assert host in self.PARSED_HOSTS

        assert len(host_selector) == 1
        with pytest.raises(HostsExhaustedError):
            assert next(host_iter)

    def test_host_selector_with_tries_not_enough_hosts(self):
        host_selector: HostSelector = HostSelector([self.HOSTS[1]], 3)

        assert len(host_selector) == 1

        host_iter: Iterator = iter(host_selector)
        host: Host = next(host_iter)
        assert host == self.PARSED_HOSTS[1]

        assert len(host_selector) == 0
        with pytest.raises(StopIteration):
            assert next(host_iter)

