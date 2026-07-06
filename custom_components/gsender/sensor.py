"""Sensor entities for the gSender integration."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from . import GSenderClient
from .const import DOMAIN, SIGNAL_GSENDER_UPDATE


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    client: GSenderClient = hass.data[DOMAIN][entry.entry_id]

    entities = [
        GSenderHostStatusSensor(client, entry),
        GSenderMachineStateSensor(client, entry),
        GSenderJobStateSensor(client, entry),
        GSenderJobProgressSensor(client, entry),
        GSenderJobElapsedSensor(client, entry),
        GSenderJobRemainingSensor(client, entry),
        GSenderJobNameSensor(client, entry),
        GSenderAlarmSensor(client, entry),
    ]
    async_add_entities(entities)


class GSenderBaseSensor(SensorEntity):
    """Base class handling the push-update wiring common to all sensors."""

    _attr_should_poll = False

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        self._client = client
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"gSender ({client.host})",
            manufacturer="Sienci Labs",
            model="gSender",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_GSENDER_UPDATE, self._handle_update)
        )

    @property
    def available(self) -> bool:
        """Entities are unavailable when the socket to gSender is down."""
        return self._client.connected

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class GSenderHostStatusSensor(GSenderBaseSensor):
    """Why (or whether) the bridge is down: online / gsender_down / host_off.

    'online' while the socket is up. While down, a low-rate TCP probe (one
    connect attempt per watchdog tick, nothing while online) distinguishes
    the gSender app being closed (PC answers, refuses the port) from the
    host PC being off entirely (no answer). Always available - its whole
    point is explaining the outage.
    """

    _attr_name = "CNC Host Status"
    _attr_icon = "mdi:desktop-tower"

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_host_status"

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        return self._client.host_status


class GSenderMachineStateSensor(GSenderBaseSensor):
    """Idle / Run / Hold / Alarm / Jog / Door / Home / Check / Sleep."""

    _attr_name = "CNC Machine State"
    _attr_icon = "mdi:printer-3d-nozzle"

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_machine_state"

    @property
    def native_value(self) -> str:
        if not self._client.controller_attached:
            return "no_controller"
        return self._client.machine_state or "unknown"

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "port_reported_inuse": self._client.port_reported_inuse,
            "serial_port": self._client.serial_port,
        }


class GSenderJobStateSensor(GSenderBaseSensor):
    """idle / running / paused workflow state."""

    _attr_name = "CNC Job State"
    _attr_icon = "mdi:progress-wrench"

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_job_state"

    @property
    def native_value(self) -> str:
        if not self._client.controller_attached:
            return "no_controller"
        return self._client.job_state or "unknown"


class GSenderJobProgressSensor(GSenderBaseSensor):
    """Job completion percentage."""

    _attr_name = "CNC Job Progress"
    _attr_icon = "mdi:progress-clock"
    _attr_native_unit_of_measurement = "%"

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_job_progress"

    @property
    def native_value(self) -> int:
        return self._client.job_progress_percent

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "sent_lines": self._client.job_sent,
            "total_lines": self._client.job_total,
            "elapsed_time": self._client.job_elapsed,
            "remaining_time": self._client.job_remaining,
        }


class GSenderJobElapsedSensor(GSenderBaseSensor):
    """Time spent on the current job."""

    _attr_name = "CNC Job Elapsed Time"
    _attr_icon = "mdi:timer-outline"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_display_precision = 0

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_job_elapsed"

    @property
    def native_value(self) -> int:
        return self._client.job_elapsed_seconds


class GSenderJobRemainingSensor(GSenderBaseSensor):
    """Estimated time remaining on the current job."""

    _attr_name = "CNC Job Remaining Time"
    _attr_icon = "mdi:timer-sand"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_display_precision = 0

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_job_remaining"

    @property
    def native_value(self) -> int:
        return self._client.job_remaining_seconds


class GSenderJobNameSensor(GSenderBaseSensor):
    """Currently loaded G-code file name."""

    _attr_name = "CNC Job File"
    _attr_icon = "mdi:file-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_job_name"

    @property
    def native_value(self) -> str:
        return self._client.job_name or "none"


class GSenderAlarmSensor(GSenderBaseSensor):
    """Last alarm/error message, useful for automations and dashboards."""

    _attr_name = "CNC Last Alarm"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_alarm"

    @property
    def native_value(self) -> str:
        return self._client.alarm_message or "none"
