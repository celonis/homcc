""" Tests for client/compilation.py"""
from pathlib import Path
from typing import List

from homcc.server.parsing import HOMCC_SERVER_CONFIG_FILENAME, ServerConfig, parse_config, load_config_file


class TestParsingConfig:
    """
    Tests for client.parsing related to config files
    """

    config: List[str] = [
        "",
        " ",
        "# HOMCC TEST CONFIG COMMENT",
        " # comment with whitespace ",
        "LIMIT=64",
        "LOG_LEVEL=DEBUG  # DEBUG",
        " port = 3633 ",
        "\tAdDrEsS=localhost",
        "verbose=TRUE",
    ]

    def test_parse_config(self):
        assert parse_config(self.config) == ServerConfig(
            limit="64", port="3633", address="localhost", log_level="DEBUG", verbose="True"
        )

    def test_load_config_file(self, tmp_path: Path):
        tmp_config_file: Path = tmp_path / HOMCC_SERVER_CONFIG_FILENAME
        tmp_config_file.write_text("\n".join(self.config))

        config_file_locations: List[Path] = [tmp_config_file]

        config: List[str] = load_config_file(config_file_locations)
        assert config == self.config
        assert parse_config(self.config) == ServerConfig(
            limit="64", port="3633", address="localhost", log_level="DEBUG", verbose="True"
        )
