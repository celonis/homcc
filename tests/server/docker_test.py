"""Test module for the docker interaction on the server side."""
import subprocess

from pytest_mock import MockerFixture

from homcc.server.docker import is_valid_docker_container


class TestDockerInteraction:
    """Unit tests for the interaction with docker."""

    class TestIsValidContainer:
        """Tests the method that checks if a docker container is a valid (existing and running) container."""

    def test_no_such_container(self, mocker: MockerFixture):
        thrown_err = subprocess.CalledProcessError(1, "cmd", output="No such container")
        mocker.patch("subprocess.run", side_effect=thrown_err)

        assert not is_valid_docker_container("foo")

    def test_unexpected_docker_output(self, mocker: MockerFixture):
        thrown_err = subprocess.CalledProcessError(
            1, "cmd", output="Some unexpected message with not zero return code."
        )
        mocker.patch("subprocess.run", side_effect=thrown_err)

        assert not is_valid_docker_container("foo")

    def test_stopped_container(self, mocker: MockerFixture):
        mocker.patch("subprocess.run", return_value=subprocess.CompletedProcess("cmd", 0, "false"))

        assert not is_valid_docker_container("foo")

    def test_valid_container(self, mocker: MockerFixture):
        mocker.patch("subprocess.run", return_value=subprocess.CompletedProcess("cmd", 0, "true"))

        assert is_valid_docker_container("foo")
