"""Constants for the CUL MAX! integration."""
from __future__ import annotations

DOMAIN = "cul_max"
PLATFORMS: list[str] = ["binary_sensor", "climate", "sensor"]

CONF_PORT = "port"
CONF_BAUDRATE = "baudrate"
CONF_GATEWAY_ADDRESS = "gateway_address"
CONF_FAKE_WALL_THERMOSTAT_ADDRESS = "fake_wall_thermostat_address"
CONF_FAKE_SHUTTER_CONTACT_ADDRESS = "fake_shutter_contact_address"
CONF_BROADCAST_TIME_DIFF = "broadcast_time_diff"

DEFAULT_BAUDRATE = 38400
DEFAULT_GATEWAY_ADDRESS = "123456"
DEFAULT_FAKE_WALL_THERMOSTAT_ADDRESS = "111111"
DEFAULT_FAKE_SHUTTER_CONTACT_ADDRESS = "222222"
DEFAULT_BROADCAST_TIME_DIFF = 10

SERVICE_PAIR_MODE = "pair_mode"
SERVICE_BROADCAST_TIME = "broadcast_time"
SERVICE_FAKE_WINDOW_CONTACT = "fake_window_contact"
SERVICE_FAKE_WALL_THERMOSTAT = "fake_wall_thermostat"

SIGNAL_NEW_DEVICE = f"{DOMAIN}_new_device"
SIGNAL_DEVICE_UPDATED = f"{DOMAIN}_device_updated"

DEVICE_TYPES = {
    0: "Cube",
    1: "HeatingThermostat",
    2: "HeatingThermostatPlus",
    3: "WallMountedThermostat",
    4: "ShutterContact",
    5: "PushButton",
    6: "virtualShutterContact",
    7: "virtualThermostat",
    8: "PlugAdapter",
    9: "new",
}

MESSAGE_TYPES = {
    "00": "PairPing", "01": "PairPong", "02": "Ack", "03": "TimeInformation",
    "10": "ConfigWeekProfile", "11": "ConfigTemperatures", "12": "ConfigValve",
    "20": "AddLinkPartner", "21": "RemoveLinkPartner", "22": "SetGroupId", "23": "RemoveGroupId",
    "30": "ShutterContactState", "40": "SetTemperature", "42": "WallThermostatControl",
    "43": "SetComfortTemperature", "44": "SetEcoTemperature", "50": "PushButtonState",
    "60": "ThermostatState", "70": "WallThermostatState", "82": "SetDisplayActualTemperature",
    "f0": "Reset", "f1": "WakeUp",
}
MESSAGE_IDS = {value: key for key, value in MESSAGE_TYPES.items()}
