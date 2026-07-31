"""Serial gateway and MAX! wire protocol implementation."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any

import serial_asyncio
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_BAUDRATE, CONF_FAKE_SHUTTER_CONTACT_ADDRESS, CONF_FAKE_WALL_THERMOSTAT_ADDRESS,
    CONF_GATEWAY_ADDRESS, CONF_PORT, DEVICE_TYPES, DOMAIN, MESSAGE_IDS, MESSAGE_TYPES,
    SIGNAL_DEVICE_UPDATED, SIGNAL_NEW_DEVICE,
)

_LOGGER = logging.getLogger(__name__)
ACK_TIMEOUT = 3
MAX_RETRIES = 3
CUL_COMMAND_TIMEOUT = 5
CUL_RECONNECT_INITIAL_DELAY = 5
CUL_RECONNECT_MAX_DELAY = 60
CUL_MIN_FIRMWARE = 152
CUL_RSSI_COMMAND = "X21"  # Enable RSSI reporting; this does not select a radio mode.
CUL_MAX_MODE_COMMAND = "Zr"  # culfw: enable MORITZ/MAX! receive mode.


@dataclass
class MaxDevice:
    """A MAX! device discovered through PairPing or status messages."""
    address: str
    device_type: str = "Unknown"
    serial: str | None = None
    firmware: str | None = None
    test_result: int | None = None
    rssi: int | None = None
    last_seen: datetime | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class PendingPacket:
    """A packet awaiting ACK."""
    frame: str
    counter: int
    source: str
    destination: str
    command: str
    retries_left: int = MAX_RETRIES
    ack_task: asyncio.Task[None] | None = None


class CulProtocol(asyncio.Protocol):
    """Line protocol used by culfw over a serial interface."""

    def __init__(self, gateway: "CulMaxGateway") -> None:
        self.gateway = gateway
        self.transport: asyncio.Transport | None = None
        self.connected = asyncio.Event()
        self.buffer = ""

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        self.connected.set()
        self.gateway.on_connected(self)

    def data_received(self, data: bytes) -> None:
        self.buffer += data.decode("ascii", errors="ignore")
        while "\n" in self.buffer or "\r" in self.buffer:
            line, _, self.buffer = self.buffer.replace("\r", "\n").partition("\n")
            if line:
                # pyserial-asyncio-fast may invoke data_received from its serial
                # reader thread. Schedule all Home Assistant state work on the loop.
                self.gateway.hass.loop.call_soon_threadsafe(
                    self.gateway.async_handle_line, line.strip()
                )

    def connection_lost(self, exc: Exception | None) -> None:
        self.gateway.on_disconnected(exc)

    def write(self, line: str) -> None:
        if self.transport is None:
            raise ConnectionError("CUL serial transport is not available")
        _LOGGER.debug("CUL TX: %s", line)
        self.transport.write(f"{line}\n".encode("ascii"))


class CulMaxGateway:
    """Manage a CUL in rfmode MAX and expose discovered MAX! devices."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.address = entry.data[CONF_GATEWAY_ADDRESS].lower()
        self.fake_wt_address = entry.data[CONF_FAKE_WALL_THERMOSTAT_ADDRESS].lower()
        self.fake_sc_address = entry.data[CONF_FAKE_SHUTTER_CONTACT_ADDRESS].lower()
        self.devices: dict[str, MaxDevice] = {}
        self._protocol: CulProtocol | None = None
        self._transport: asyncio.Transport | None = None
        self._counter = 0
        self._pending: list[PendingPacket] = []
        self._pair_mode_until: float = 0
        self._stopping = False
        self._initialized = False
        self._reconnect_task: asyncio.Task[None] | None = None
        self._command_waiters: list[tuple[str, asyncio.Future[str]]] = []
        self.cul_firmware: str | None = None
        self.cul_mode: str | None = None

    async def async_connect(self) -> None:
        """Open, validate, and initialise the CUL for MAX! operation."""
        self._stopping = False
        await self._async_open_and_initialize()

    async def _async_open_and_initialize(self) -> None:
        """Open the port once and perform the CUL firmware and RF-mode handshake."""
        if self._transport is not None:
            return
        self._initialized = False
        loop = asyncio.get_running_loop()
        # Keep the protocol instance before opening the port. Some serial backends return
        # before invoking connection_made(), so using the discarded return value creates
        # a race and incorrectly reports an unavailable transport.
        protocol = CulProtocol(self)
        self._protocol = protocol
        transport, _ = await serial_asyncio.create_serial_connection(
            loop, lambda: protocol, self.entry.data[CONF_PORT], baudrate=self.entry.data[CONF_BAUDRATE]
        )
        self._transport = transport
        try:
            await asyncio.wait_for(protocol.connected.wait(), timeout=CUL_COMMAND_TIMEOUT)
            version = await self._async_command("V", "V")
            self._validate_firmware(version)
            # FHEM's CUL driver uses X21 followed by Zr for rfmode MAX:
            # X21 enables RSSI reporting; Zr activates the MORITZ/MAX! receiver.
            self._write_raw(CUL_RSSI_COMMAND)
            self._write_raw(CUL_MAX_MODE_COMMAND)
            # Zr does not emit a dedicated acknowledgement. A working MAX! receiver
            # is verified by its ability to send/receive Z frames after setup.
            # Firmware >= 1.52 accepts the MAX source ID; Zw configures fake wall thermostat ID.
            self._write_raw(f"Za{self.address}")
            self._write_raw(f"Zw{self.fake_wt_address}")
            self._initialized = True
            _LOGGER.info("CUL %s initialized for MAX! mode (%s)", self.entry.data[CONF_PORT], self.cul_firmware)
        except Exception:
            transport.close()
            self._transport = None
            self._protocol = None
            raise

    async def async_disconnect(self) -> None:
        """Close transport and cancel packet/reconnection timers."""
        self._stopping = True
        self._initialized = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        for _, waiter in self._command_waiters:
            if not waiter.done():
                waiter.cancel()
        self._command_waiters.clear()
        for packet in self._pending:
            if packet.ack_task:
                packet.ack_task.cancel()
        self._pending.clear()
        if self._transport:
            self._transport.close()
            self._transport = None

    async def _async_command(self, command: str, response_prefix: str) -> str:
        """Send an ASCII CUL command and wait for its matching response line."""
        if not self._protocol:
            raise ConnectionError("CUL serial transport is unavailable")
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._command_waiters.append((response_prefix, future))
        self._write_raw(command)
        try:
            return await asyncio.wait_for(future, timeout=CUL_COMMAND_TIMEOUT)
        except TimeoutError as err:
            raise ConnectionError(f"CUL did not answer command {command!r}") from err
        finally:
            self._command_waiters = [(prefix, waiter) for prefix, waiter in self._command_waiters if waiter is not future]

    def _write_raw(self, command: str) -> None:
        if not self._protocol:
            raise ConnectionError("CUL serial transport is disconnected")
        self._protocol.write(command)

    def _validate_firmware(self, response: str) -> None:
        """Accept a-culfw or culfw 1.52+, which is required for stable MAX! support."""
        self.cul_firmware = response
        lower = response.lower()
        if "a-culfw" in lower:
            return
        import re
        match = re.search(r"V\s+(\d+)\.(\d+)", response)
        if not match:
            raise ConnectionError(f"Unrecognised CUL firmware response: {response!r}")
        firmware = int(match.group(1)) * 100 + int(match.group(2))
        if firmware < CUL_MIN_FIRMWARE:
            raise ConnectionError(f"CUL firmware {match.group(1)}.{match.group(2)} is too old; version 1.52 or newer is required")

    def on_connected(self, protocol: CulProtocol) -> None:
        self._protocol = protocol
        _LOGGER.info("Connected to CUL serial gateway %s", self.entry.data[CONF_PORT])

    def on_disconnected(self, exc: Exception | None) -> None:
        was_connected = self._transport is not None
        self._protocol = None
        self._transport = None
        if exc:
            _LOGGER.warning("CUL serial connection lost: %s", exc)
        elif was_connected and not self._stopping:
            _LOGGER.warning("CUL serial connection closed; waiting for the stick to return")
        if self._initialized and not self._stopping and self._reconnect_task is None:
            self._reconnect_task = self.hass.async_create_task(self._async_reconnect_loop())

    async def _async_reconnect_loop(self) -> None:
        """Reconnect with bounded backoff after an unplug/replug event."""
        delay = CUL_RECONNECT_INITIAL_DELAY
        try:
            while not self._stopping and self._transport is None:
                await asyncio.sleep(delay)
                try:
                    await self._async_open_and_initialize()
                    _LOGGER.info("CUL MAX! gateway reconnected")
                    return
                except (OSError, ConnectionError) as err:
                    _LOGGER.debug("CUL reconnect failed; retrying in %s seconds: %s", delay, err)
                    delay = min(delay * 2, CUL_RECONNECT_MAX_DELAY)
        finally:
            self._reconnect_task = None

    async def async_enable_pair_mode(self, duration: int = 60) -> None:
        self._pair_mode_until = asyncio.get_running_loop().time() + duration
        _LOGGER.info("MAX! pairing enabled for %s seconds", duration)

    async def async_broadcast_time(self) -> None:
        await self.async_send("TimeInformation", "000000", self._time_payload(), flags="04")

    async def async_send_fake_window_contact(self, destination: str, is_open: bool, group_id: int = 0) -> None:
        state = "12" if is_open else "10"
        await self.async_send("ShutterContactState", destination, state, source=self.fake_sc_address,
                              flags="04" if group_id else "06", group_id=group_id)

    async def async_send_fake_wall_thermostat(self, destination: str, desired: float, measured: float, group_id: int = 0) -> None:
        desired_encoded = int(desired * 2) & 0x7F
        measured_encoded = max(0, int(measured * 10))
        first = ((measured_encoded & 0x100) >> 1) | desired_encoded
        payload = f"{first:02x}{measured_encoded & 0xFF:02x}"
        await self.async_send("WallThermostatControl", destination, payload, source=self.fake_wt_address,
                              flags="04" if group_id else "00", group_id=group_id)

    async def async_send(self, command: str, destination: str, payload: str = "", *, source: str | None = None,
                         flags: str = "00", group_id: int = 0) -> None:
        """Send a MAX! packet, retrying it only when an ACK is required."""
        if command not in MESSAGE_IDS:
            raise ValueError(f"Unsupported MAX! command: {command}")
        source = (source or self.address).lower()
        destination = destination.lower()
        self._counter = (self._counter + 1) & 0xFF
        counter = self._counter
        body = f"{counter:02x}{flags}{MESSAGE_IDS[command]}{source}{destination}{group_id:02x}{payload}"
        frame = f"{len(body) // 2:02x}{body}"
        self._write_frame(frame)
        if destination != "000000":
            packet = PendingPacket(frame, counter, source, destination, command)
            self._pending.append(packet)
            packet.ack_task = self.hass.async_create_task(self._async_retry(packet))

    async def _async_retry(self, packet: PendingPacket) -> None:
        while packet.retries_left:
            await asyncio.sleep(ACK_TIMEOUT)
            if packet not in self._pending:
                return
            packet.retries_left -= 1
            _LOGGER.debug("Retrying MAX! %s to %s (%s left)", packet.command, packet.destination, packet.retries_left)
            self._write_frame(packet.frame)
        if packet in self._pending:
            self._pending.remove(packet)
            _LOGGER.warning("MAX! command %s to %s was not acknowledged", packet.command, packet.destination)

    def _write_frame(self, frame: str) -> None:
        if not self._protocol:
            raise ConnectionError("CUL serial transport is disconnected")
        self._protocol.write(f"Zs{frame}")

    @staticmethod
    def _time_payload() -> str:
        now = datetime.now().astimezone()
        return f"{now.year - 2000:02x}{now.day:02x}{now.hour:02x}{now.minute | ((now.month & 0x0C) << 4):02x}{now.second | ((now.month & 0x03) << 6):02x}"

    @staticmethod
    def _parse_frame(line: str) -> tuple[int, int, str, str, str, str, int, str, int | None] | None:
        """Parse a MAX! Z frame and its optional trailing CUL RSSI byte.

        With `X21` enabled, culfw appends one RSSI byte to received radio frames.
        That byte is not part of the MAX! length field and must be removed first.
        """
        if not line.startswith("Z") or len(line) < 21:
            return None
        raw = line[1:]
        try:
            length = int(raw[0:2], 16)
            expected_length = 2 + length * 2
            rssi: int | None = None
            if len(raw) == expected_length + 2:
                rssi_raw = int(raw[-2:], 16)
                rssi = (rssi_raw - 256) / 2 - 74 if rssi_raw >= 128 else rssi_raw / 2 - 74
                raw = raw[:-2]
            if len(raw) != expected_length:
                return None
            return (
                length,
                int(raw[2:4], 16),
                raw[4:6],
                raw[6:8].lower(),
                raw[8:14].lower(),
                raw[14:20].lower(),
                int(raw[20:22], 16),
                raw[22:].lower(),
                rssi,
            )
        except ValueError:
            return None

    def async_handle_line(self, line: str) -> None:
        """Process one line received from CUL firmware."""
        _LOGGER.debug("CUL RX: %s", line)
        for prefix, waiter in list(self._command_waiters):
            if line.startswith(prefix) and not waiter.done():
                waiter.set_result(line)
                return
        parsed = self._parse_frame(line)
        if not parsed:
            return
        _, counter, flags, message_id, source, destination, group_id, payload, rssi = parsed
        command = MESSAGE_TYPES.get(message_id, message_id)
        if source in {self.address, self.fake_wt_address, self.fake_sc_address}:
            return
        if command == "Ack":
            self._handle_ack(counter, source, destination, payload)
            return
        if command == "PairPing":
            self._handle_pair_ping(source, destination, payload)
            return
        if command == "TimeInformation" and destination == self.address:
            # Reply to an empty request, or correct clocks exceeding the configured tolerance.
            if not payload or self._time_difference_exceeds_tolerance(payload):
                self.hass.async_create_task(self.async_send("TimeInformation", source, self._time_payload(), flags="04"))
            return
        if command in {"ShutterContactState", "WallThermostatState", "WallThermostatControl", "ThermostatState", "PushButtonState", "SetTemperature"}:
            self._update_device_from_state(source, command, payload, group_id, rssi)

    def _time_difference_exceeds_tolerance(self, payload: str) -> bool:
        """Return whether a MAX! TimeInformation payload is outside its allowed drift."""
        if len(payload) < 10:
            return True
        try:
            year = 2000 + int(payload[0:2], 16)
            day = int(payload[2:4], 16)
            hour_byte = int(payload[4:6], 16)
            minute_byte = int(payload[6:8], 16)
            second_byte = int(payload[8:10], 16)
            month = ((minute_byte >> 6) << 2) | (second_byte >> 6)
            received = datetime(year, month, day, hour_byte & 0x1F, minute_byte & 0x3F, second_byte & 0x3F, tzinfo=datetime.now().astimezone().tzinfo)
            tolerance = self.entry.data.get("broadcast_time_diff", 10)
            return abs((datetime.now().astimezone() - received).total_seconds()) > tolerance
        except ValueError:
            return True

    def _device(self, address: str, device_type: str | None = None) -> MaxDevice:
        """Return a discovered device and optionally set its inferred MAX! type."""
        new = address not in self.devices
        device = self.devices.setdefault(address, MaxDevice(address=address))
        if device_type and device.device_type == "Unknown":
            device.device_type = device_type
        device.last_seen = datetime.now().astimezone()
        if new:
            async_dispatcher_send(self.hass, SIGNAL_NEW_DEVICE, self.entry.entry_id, address)
        return device

    def _publish(self, address: str) -> None:
        async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, address)

    def _handle_ack(self, counter: int, source: str, destination: str, payload: str) -> None:
        for packet in list(self._pending):
            if packet.counter == counter and packet.source == destination and packet.destination == source:
                self._pending.remove(packet)
                if packet.ack_task:
                    packet.ack_task.cancel()
                if payload and (int(payload[:2], 16) & 0x80):
                    _LOGGER.warning("MAX! NACK from %s for %s", source, packet.command)
                return

    def _handle_pair_ping(self, source: str, destination: str, payload: str) -> None:
        if len(payload) < 6:
            return
        firmware, devtype, testresult = int(payload[0:2], 16), int(payload[2:4], 16), int(payload[4:6], 16)
        device = self._device(source)
        device.device_type = DEVICE_TYPES.get(devtype, f"Unknown ({devtype})")
        device.firmware = f"{firmware >> 4}.{firmware & 0x0F}"
        device.test_result = testresult
        try:
            device.serial = bytes.fromhex(payload[6:]).decode("ascii", errors="replace")
        except ValueError:
            device.serial = None
        self._publish(source)
        if destination in {"000000", self.address} and (asyncio.get_running_loop().time() < self._pair_mode_until or destination == self.address):
            self.hass.async_create_task(self.async_send("PairPong", source, "00"))

    async def async_set_target_temperature(self, destination: str, temperature: float, *, mode: int = 1, group_id: int | None = None) -> None:
        """Set a thermostat target temperature using FHEM MAX.pm's SetTemperature encoding."""
        if not 4.5 <= temperature <= 30.5 or (temperature * 2) % 1:
            raise ValueError("Temperature must be between 4.5 and 30.5 °C in 0.5 °C steps")
        device = self.devices.get(destination)
        group = group_id if group_id is not None else int(device.data.get("group_id", 0) if device else 0)
        payload = f"{(int(temperature * 2) & 0x3F) | (mode << 6):02x}"
        await self.async_send("SetTemperature", destination, payload, group_id=group, flags="04" if group else "00")

    async def async_set_group_id(self, destination: str, group_id: int) -> None:
        """Write a MAX! group ID or remove it for zero."""
        if not 0 <= group_id <= 255:
            raise ValueError("Group ID must be between 0 and 255")
        await self.async_send("SetGroupId" if group_id else "RemoveGroupId", destination, f"{group_id:02x}")

    async def async_configure_temperatures(self, destination: str, *, comfort: float, eco: float,
                                           maximum: float, minimum: float, offset: float,
                                           window_open: float, window_duration: int, group_id: int = 0) -> None:
        """Send the ConfigTemperatures payload as encoded by FHEM MAX.pm."""
        values = (comfort, eco, maximum, minimum, window_open)
        if any(not 4.5 <= value <= 30.5 or (value * 2) % 1 for value in values):
            raise ValueError("MAX! temperatures must be 4.5–30.5 °C in 0.5 °C steps")
        if not -3.5 <= offset <= 3.5 or (offset * 2) % 1 or not 0 <= window_duration <= 60 or window_duration % 5:
            raise ValueError("Invalid offset or window-open duration")
        payload = f"{int(comfort*2):02x}{int(eco*2):02x}{int(maximum*2):02x}{int(minimum*2):02x}{int((offset+3.5)*2):02x}{int(window_open*2):02x}{window_duration//5:02x}"
        await self.async_send("ConfigTemperatures", destination, payload, group_id=group_id, flags="04" if group_id else "00")

    async def async_configure_valve(self, destination: str, *, boost_duration: int, boost_position: int,
                                    decalc_day: int, decalc_hour: int, maximum: int, offset: int) -> None:
        """Send the ConfigValve payload as encoded by FHEM MAX.pm."""
        boost_codes = {0: 0, 5: 1, 10: 2, 15: 3, 20: 4, 25: 5, 30: 6, 60: 7}
        if boost_duration not in boost_codes or not all(0 <= value <= 100 for value in (boost_position, maximum, offset)):
            raise ValueError("Invalid valve configuration")
        if not 0 <= decalc_day <= 6 or not 0 <= decalc_hour < 24:
            raise ValueError("Invalid decalcification time")
        payload = f"{(boost_codes[boost_duration] << 5) | (boost_position // 5):02x}{(decalc_day << 5) | decalc_hour:02x}{int(maximum * 255 / 100):02x}{int(offset * 255 / 100):02x}"
        await self.async_send("ConfigValve", destination, payload)

    async def async_associate(self, destination: str, partner: str, partner_type: int, *, remove: bool = False) -> None:
        """Add or remove a MAX! link partner."""
        if not 0 <= partner_type <= 255:
            raise ValueError("Invalid MAX! device type")
        await self.async_send("RemoveLinkPartner" if remove else "AddLinkPartner", destination, f"{partner.lower()}{partner_type:02x}")

    async def async_factory_reset(self, destination: str) -> None:
        """Reset a MAX! device; it must be paired again afterwards."""
        await self.async_send("Reset", destination)

    async def async_set_week_profile_part(self, destination: str, day: int, part: int, profile: str) -> None:
        """Send one seven-control-point ConfigWeekProfile packet."""
        if not 0 <= day <= 6 or part not in {0, 1} or len(profile) != 28:
            raise ValueError("Invalid week-profile day, part, or packet length")
        await self.async_send("ConfigWeekProfile", destination, f"{part:x}{day:x}{profile}")

    def _update_device_from_state(self, source: str, command: str, payload: str, group_id: int, rssi: int | None = None) -> None:
        """Decode state payloads using the layouts from FHEM's MAX.pm.

        Existing FHEM-paired devices often do not send PairPing again. Infer their
        type directly from their normal status telegram, just as FHEM MAX.pm does.
        """
        device_type = {
            "ShutterContactState": "ShutterContact",
            "PushButtonState": "PushButton",
            "ThermostatState": "HeatingThermostat",
            "WallThermostatState": "WallMountedThermostat",
            "WallThermostatControl": "WallMountedThermostat",
        }.get(command)
        device = self._device(source, device_type)
        if rssi is not None:
            device.rssi = rssi
        data = device.data
        data.update({"last_command": command, "last_payload": payload, "group_id": group_id})
        try:
            raw = bytes.fromhex(payload)
        except ValueError:
            _LOGGER.debug("Discarding malformed %s payload from %s: %s", command, source, payload)
            return

        if command == "ShutterContactState" and raw:
            flags = raw[0]
            data["window_open"] = (flags & 0x03) != 0
            data["rf_error"] = bool(flags & 0x40)
            data["battery"] = "low" if flags & 0x80 else "ok"
        elif command == "PushButtonState" and len(raw) >= 2:
            flags, state = raw[0], raw[1]
            data["button_state"] = state
            data["rf_error"] = bool(flags & 0x40)
            data["battery"] = "low" if flags & 0x80 else "ok"
        elif command == "ThermostatState" and len(raw) >= 3:
            flags, valve, target_raw = raw[:3]
            mode = flags & 0x03
            data["mode"] = ("auto", "manual", "temporary", "boost")[mode]
            data["valve_position"] = valve
            data["target_temperature"] = (target_raw & 0x7F) / 2
            data["panel_locked"] = bool(flags & 0x20)
            data["rf_error"] = bool(flags & 0x40)
            data["battery"] = "low" if flags & 0x80 else "ok"
            if mode != 2 and len(raw) >= 5:
                temperature = (((raw[3] & 0x01) << 8) | raw[4]) / 10
                if temperature >= 1:
                    data["measured_temperature"] = temperature
            if mode == 2 and len(raw) >= 6:
                data["until_raw"] = raw[3:6].hex()
        elif command in {"WallThermostatControl", "WallThermostatState"} and len(raw) >= 2:
            temp_low: int | None = None
            if len(raw) == 2:
                desired_raw, temp_low = raw
            else:
                flags = raw[0]
                data["mode"] = ("auto", "manual", "temporary", "boost")[flags & 0x03]
                data["panel_locked"] = bool(flags & 0x20)
                data["rf_error"] = bool(flags & 0x40)
                data["battery"] = "low" if flags & 0x80 else "ok"
                data["display_actual_temperature"] = bool(raw[1])
                desired_raw = raw[2]
                if len(raw) >= 7:
                    temp_low = raw[-1]
            data["target_temperature"] = (desired_raw & 0x7F) / 2
            if temp_low is not None:
                data["measured_temperature"] = (((desired_raw & 0x80) << 1) | temp_low) / 10
        elif command == "SetTemperature" and raw:
            data["mode"] = ("auto", "manual", "temporary", "boost")[raw[0] >> 6]
            data["target_temperature"] = (raw[0] & 0x3F) / 2
        self._publish(source)
