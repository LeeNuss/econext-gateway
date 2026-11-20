#!/usr/bin/with-contenv bashio
set -e

ECONEXT_SERIAL_PORT="$(bashio::config 'serial_port')"
ECONEXT_LOG_LEVEL="$(bashio::config 'log_level' | tr '[:lower:]' '[:upper:]')"
ECONEXT_CLOCK_SYNC_ENABLED="$(bashio::config 'clock_sync')"
# /data survives restarts and updates: bus address, thermostat pairing.
ECONEXT_STATE_DIR=/data
export ECONEXT_SERIAL_PORT ECONEXT_LOG_LEVEL ECONEXT_CLOCK_SYNC_ENABLED \
    ECONEXT_STATE_DIR

bashio::log.info "Starting ecoNEXT gateway on ${ECONEXT_SERIAL_PORT}"
exec uvicorn econext_gateway.main:app --host 0.0.0.0 --port 8000
