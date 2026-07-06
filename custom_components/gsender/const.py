"""Constants for the gSender integration."""

DOMAIN = "gsender"

CONF_SERIAL_PORT = "serial_port"
CONF_BAUDRATE = "baudrate"
CONF_FIRMWARE = "firmware"

DEFAULT_PORT = 8000
DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"
DEFAULT_BAUDRATE = 115200
# gSender calls this "defaultFirmware" in its open options: "Grbl" | "grblHAL"
DEFAULT_FIRMWARE = "grblHAL"
FIRMWARE_TYPES = ["Grbl", "grblHAL"]

SIGNAL_GSENDER_UPDATE = "gsender_update"

# Events fired on the HA bus for automations ("job finished" notification
# etc.). Derived from workflow:state transitions, NOT from gSender's task:*
# events (those relate to shell-command tasks, and their payload shapes are
# unverified).
EVENT_JOB_STARTED = "gsender_job_started"
EVENT_JOB_PAUSED = "gsender_job_paused"
EVENT_JOB_RESUMED = "gsender_job_resumed"
# NOTE: fired when workflow goes running/paused -> idle. gSender does not
# distinguish "completed" from "stopped by user" at this level.
EVENT_JOB_FINISHED = "gsender_job_finished"
EVENT_ALARM = "gsender_alarm"

# Host status sensor states. Only probed while the socket is DOWN
# (TCP connect attempt to the gSender port - refused means the PC is up,
# timeout/no-route means the PC is off/unreachable). No probing at all
# while connected.
HOST_STATUS_ONLINE = "online"  # socket to gSender is up
HOST_STATUS_GSENDER_DOWN = "gsender_down"  # PC up, gSender/Remote Mode not listening
HOST_STATUS_HOST_OFF = "host_off"  # PC unreachable (off, or firewalled/dropped)
HOST_STATUS_UNKNOWN = "unknown"  # not determined yet

# GRBL active states (from gSender's controllers/Grbl/constants.js)
GRBL_ACTIVE_STATES = [
    "Idle",
    "Run",
    "Hold",
    "Jog",
    "Alarm",
    "Door",
    "Check",
    "Home",
    "Sleep",
]
