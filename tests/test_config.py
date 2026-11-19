"""Unit tests for configuration module."""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from econext_gateway.core.config import Settings, setup_logging


class TestSettings:
    """Tests for Settings class."""

    def test_default_values(self):
        """Test settings have sensible defaults."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()

        assert settings.serial_port == "/dev/econext"
        assert settings.serial_baud == 115200
        assert settings.api_host == "0.0.0.0"
        assert settings.api_port == 8000
        assert settings.log_level == "INFO"
        assert settings.poll_interval == 10.0
        assert settings.request_timeout == 1.5
        assert settings.destination_address == 1
        assert settings.params_per_request == 100

    def test_env_override_serial_port(self):
        """Test serial port override from environment."""
        with patch.dict(os.environ, {"ECONEXT_SERIAL_PORT": "/dev/ttyACM0"}):
            settings = Settings()

        assert settings.serial_port == "/dev/ttyACM0"

    def test_env_override_serial_baud(self):
        """Test baud rate override from environment."""
        with patch.dict(os.environ, {"ECONEXT_SERIAL_BAUD": "115200"}):
            settings = Settings()

        assert settings.serial_baud == 115200

    def test_env_override_api_host(self):
        """Test API host override from environment."""
        with patch.dict(os.environ, {"ECONEXT_API_HOST": "127.0.0.1"}):
            settings = Settings()

        assert settings.api_host == "127.0.0.1"

    def test_env_override_api_port(self):
        """Test API port override from environment."""
        with patch.dict(os.environ, {"ECONEXT_API_PORT": "9000"}):
            settings = Settings()

        assert settings.api_port == 9000

    def test_env_override_log_level(self):
        """Test log level override from environment."""
        with patch.dict(os.environ, {"ECONEXT_LOG_LEVEL": "DEBUG"}):
            settings = Settings()

        assert settings.log_level == "DEBUG"

    def test_env_override_poll_interval(self):
        """Test poll interval override from environment."""
        with patch.dict(os.environ, {"ECONEXT_POLL_INTERVAL": "5.0"}):
            settings = Settings()

        assert settings.poll_interval == 5.0

    def test_env_override_destination(self):
        """Test destination address override from environment."""
        with patch.dict(os.environ, {"ECONEXT_DESTINATION_ADDRESS": "237"}):
            settings = Settings()

        assert settings.destination_address == 237

    def test_validity_defaults(self):
        """Reset counter, sentinels and the stale limit have defaults."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()

        assert settings.reset_counter_param == "resetCounter"
        assert settings.validity_sentinel_names == ("TempCWU", "HoldingRegister_6061", "HoldingRegister_6271")
        assert settings.stale_after is None  # the handler then uses three poll intervals

    def test_env_override_validity(self):
        """Sentinels are a comma separated list; blanks are dropped."""
        env = {
            "ECONEXT_RESET_COUNTER_PARAM": "boots",
            "ECONEXT_VALIDITY_SENTINELS": " TempCWU , TempBuforUp,",
            "ECONEXT_STALE_AFTER": "45",
        }
        with patch.dict(os.environ, env):
            settings = Settings()

        assert settings.reset_counter_param == "boots"
        assert settings.validity_sentinel_names == ("TempCWU", "TempBuforUp")
        assert settings.stale_after == 45.0

    def test_empty_env_disables_validity_rules(self):
        """An empty value switches a rule off."""
        with patch.dict(os.environ, {"ECONEXT_RESET_COUNTER_PARAM": "", "ECONEXT_VALIDITY_SENTINELS": ""}):
            settings = Settings()

        assert settings.reset_counter_param == ""
        assert settings.validity_sentinel_names == ()

    def test_empty_stale_after_means_the_default(self):
        """As for the other two settings, an empty value is not an error."""
        with patch.dict(os.environ, {"ECONEXT_STALE_AFTER": ""}):
            settings = Settings()

        assert settings.stale_after is None

    @pytest.mark.parametrize("value", ["0", "-5"])
    def test_stale_after_must_be_positive(self, value):
        """With 0 the data would never be ready, so the gateway refuses to start."""
        with patch.dict(os.environ, {"ECONEXT_STALE_AFTER": value}), pytest.raises(ValidationError):
            Settings()

    def test_env_prefix(self):
        """Test that non-prefixed env vars are ignored."""
        with patch.dict(os.environ, {"SERIAL_PORT": "/dev/other"}, clear=True):
            settings = Settings()

        assert settings.serial_port == "/dev/econext"


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_setup_logging_info(self):
        """Test setting up INFO logging."""
        setup_logging("INFO")

    def test_setup_logging_debug(self):
        """Test setting up DEBUG logging."""
        setup_logging("DEBUG")

    def test_setup_logging_case_insensitive(self):
        """Test log level is case insensitive."""
        setup_logging("debug")

    def test_setup_logging_invalid_defaults_to_info(self):
        """Test invalid level defaults to INFO."""
        setup_logging("INVALID")
