""" Tests for client/compilation.py"""
from pathlib import Path
from typing import List

from homcc.common.parsing import HOMCC_CONFIG_FILENAME
from homcc.server.parsing import (
    SCHROOT_CONF_FILENAME,
    ServerConfig,
    parse_config,
    load_schroot_profiles,
)


class TestParsingConfig:
    """
    Tests for client.parsing related to config files
    """

    config: List[str] = [
        "[homccd]",  # config section
        "# HOMCC TEST CONFIG COMMENT",  # comment line
        "LIMIT=64",  # attribute with capitalized key
        "LOG_LEVEL=DEBUG ",  # attribute with trailing whitespace
        "port = 3633 ",  # attribute with whitespace
        "AdDrEsS=localhost",  # attribute with changing capitalization
        "verbose=TRUE",  # boolean attribute
    ]

    def test_parse_config_file(self, tmp_path: Path):
        tmp_config_file: Path = tmp_path / HOMCC_CONFIG_FILENAME
        tmp_config_file.write_text("\n".join(self.config))

        assert parse_config([tmp_config_file]) == ServerConfig(
            limit=64, port=3633, address="localhost", log_level="DEBUG", verbose=True
        )


class TestLoadSchrootProfiles:
    """
    Tests for client.load_schroot_profiles related to schroot config files
    """

    schroot_config: List[str] = [
        "[foobar]",
        "description=FooBar",
        "directory=/var/chroot/foo",
        "aliases=foo,bar",
        "",
        "[baz]",
        "description=Baz",
        "directory=/var/chroot/baz",
    ]

    def test_load_schroot_profiles(self, tmp_path: Path):
        tmp_schroot_config_file: Path = tmp_path / SCHROOT_CONF_FILENAME
        tmp_schroot_config_file.write_text("\n".join(self.schroot_config))

        schroot_config_file_locations: List[Path] = [tmp_schroot_config_file]
        schroot_profiles: List[str] = load_schroot_profiles(schroot_config_file_locations)

        assert len(schroot_profiles) == 4
        assert "foobar" in schroot_profiles
        assert "foo" in schroot_profiles
        assert "bar" in schroot_profiles
        assert "baz" in schroot_profiles
