"""Config flow for the gSender integration."""
from __future__ import annotations

import logging
from typing import Any

import socketio
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import (
    CONF_BAUDRATE,
    CONF_FIRMWARE,
    CONF_SERIAL_PORT,
    DEFAULT_BAUDRATE,
    DEFAULT_FIRMWARE,
    DEFAULT_PORT,
    DEFAULT_SERIAL_PORT,
    DOMAIN,
    FIRMWARE_TYPES,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_SERIAL_PORT, default=DEFAULT_SERIAL_PORT): str,
        vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): int,
        vol.Required(CONF_FIRMWARE, default=DEFAULT_FIRMWARE): vol.In(FIRMWARE_TYPES),
    }
)


async def _test_connection(host: str, port: int) -> bool:
    """Try a quick connect/disconnect to confirm the remote server is reachable."""
    sio = socketio.AsyncClient()
    url = f"http://{host}:{port}"
    try:
        await sio.connect(url, transports=["websocket", "polling"], wait_timeout=5)
        await sio.disconnect()
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("gSender connection test failed for %s: %s", url, err)
        return False


class GSenderConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for gSender."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            if await _test_connection(host, port):
                return self.async_create_entry(
                    title=f"gSender ({host})",
                    data=user_input,
                )
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host/port/serial port without removing the entry.

        Host changes are expected (CNC-PC is on DHCP), so the unique_id is
        updated along with the data rather than pinned.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            unique_id = f"{host}:{port}"

            for other in self._async_current_entries():
                if other.entry_id != entry.entry_id and other.unique_id == unique_id:
                    return self.async_abort(reason="already_configured")

            if await _test_connection(host, port):
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    title=f"gSender ({host})",
                    data=user_input,
                )
            errors["base"] = "cannot_connect"

        defaults = user_input or entry.data
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults[CONF_HOST]): str,
                vol.Required(CONF_PORT, default=defaults[CONF_PORT]): int,
                vol.Required(CONF_SERIAL_PORT, default=defaults[CONF_SERIAL_PORT]): str,
                vol.Required(
                    CONF_BAUDRATE,
                    default=defaults.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
                ): int,
                vol.Required(
                    CONF_FIRMWARE,
                    default=defaults.get(CONF_FIRMWARE, DEFAULT_FIRMWARE),
                ): vol.In(FIRMWARE_TYPES),
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )
