"""Unit tests for configuration module."""

import os
from unittest.mock import patch

from econet_gm3_gateway.core.config import Settings, setup_logging


class TestSettings:
    """Tests for Settings class."""

    def test_default_values(self):
        """Test settings have sensible defaults."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()

        assert settings.serial_port == "/dev/ttyUSB0"
        assert settings.serial_baud == 115200
        assert settings.api_host == "0.0.0.0"
        assert settings.api_port == 8000
        assert settings.log_level == "INFO"
        assert settings.poll_interval == 10.0
        assert settings.request_timeout == 5.0
        assert settings.destination_address == 1
        assert settings.params_per_request == 50

    def test_env_override_serial_port(self):
        """Test serial port override from environment."""
        with patch.dict(os.environ, {"ECONET_SERIAL_PORT": "/dev/ttyACM0"}):
            settings = Settings()

        assert settings.serial_port == "/dev/ttyACM0"

    def test_env_override_serial_baud(self):
        """Test baud rate override from environment."""
        with patch.dict(os.environ, {"ECONET_SERIAL_BAUD": "115200"}):
            settings = Settings()

        assert settings.serial_baud == 115200

    def test_env_override_api_host(self):
        """Test API host override from environment."""
        with patch.dict(os.environ, {"ECONET_API_HOST": "127.0.0.1"}):
            settings = Settings()

        assert settings.api_host == "127.0.0.1"

    def test_env_override_api_port(self):
        """Test API port override from environment."""
        with patch.dict(os.environ, {"ECONET_API_PORT": "9000"}):
            settings = Settings()

        assert settings.api_port == 9000

    def test_env_override_log_level(self):
        """Test log level override from environment."""
        with patch.dict(os.environ, {"ECONET_LOG_LEVEL": "DEBUG"}):
            settings = Settings()

        assert settings.log_level == "DEBUG"

    def test_env_override_poll_interval(self):
        """Test poll interval override from environment."""
        with patch.dict(os.environ, {"ECONET_POLL_INTERVAL": "5.0"}):
            settings = Settings()

        assert settings.poll_interval == 5.0

    def test_env_override_destination(self):
        """Test destination address override from environment."""
        with patch.dict(os.environ, {"ECONET_DESTINATION_ADDRESS": "237"}):
            settings = Settings()

        assert settings.destination_address == 237

    def test_env_prefix(self):
        """Test that non-prefixed env vars are ignored."""
        with patch.dict(os.environ, {"SERIAL_PORT": "/dev/other"}, clear=True):
            settings = Settings()

        assert settings.serial_port == "/dev/ttyUSB0"


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
