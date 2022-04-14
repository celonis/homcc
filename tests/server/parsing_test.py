""" Tests for client/compilation.py"""
from pathlib import Path
from typing import Dict, List

from homcc.server.parsing import parse_config, load_config_file


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
        "LIFETIME=42  # Answer to the Ultimate Question of Life, the Universe, and Everything",
        " port = 3633 ",
        "\tAdDrEsS=lOcAlHoSt",
    ]

    def test_parse_config(self):
        parsed_config = parse_config(self.config)

        assert parsed_config["limit"] == "64"
        assert parsed_config["lifetime"] == "42"
        assert parsed_config["port"] == "3633"
        assert parsed_config["address"] == "localhost"

    def test_load_config_file(self, tmp_path):
        tmp_config_file: Path = tmp_path / "server.conf"
        tmp_config_file.write_text("\n".join(self.config))

        config_file_locations: List[Path] = [tmp_config_file]

        config: List[str] = load_config_file(config_file_locations)

        assert config == self.config

        parsed_config: Dict[str, str] = parse_config(config)

        assert parsed_config["limit"] == "64"
        assert parsed_config["lifetime"] == "42"
        assert parsed_config["port"] == "3633"
        assert parsed_config["address"] == "localhost"
