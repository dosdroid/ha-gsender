"""Diagnostics support for the gSender integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import GSenderClient
from .const import DOMAIN

TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    client: GSenderClient = hass.data[DOMAIN][entry.entry_id]

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "client": {
            "connected": client.connected,
            "host_status": client.host_status,
            "controller_attached": client.controller_attached,
            "port_reported_inuse": client.port_reported_inuse,
            "machine_state": client.machine_state,
            "job_state": client.job_state,
            "job_name": client.job_name,
            "job_sent": client.job_sent,
            "job_total": client.job_total,
            "job_elapsed": client.job_elapsed,
            "job_remaining": client.job_remaining,
            "alarm_message": client.alarm_message,
        },
    }
