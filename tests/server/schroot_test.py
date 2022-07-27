"""Test module for the docker interaction on the server side."""
import pytest

from homcc.server.schroot import get_schroot_profiles, is_schroot_available, is_valid_schroot_profile


class TestSchrootInteraction:
    """Unit tests for the interaction with schroot."""

    @pytest.mark.schroot
    def test_schroot_profiles(self, schroot_profile: str):
        assert is_schroot_available()
        assert schroot_profile in get_schroot_profiles()
        assert is_valid_schroot_profile(schroot_profile)

        assert not is_valid_schroot_profile("should_not_exist")
