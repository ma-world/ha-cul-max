"""Protocol-oriented tests that do not need physical CUL hardware."""
from pathlib import Path
import ast
import unittest

GATEWAY = Path(__file__).parents[1] / "custom_components" / "cul_max" / "gateway.py"


def parse_frame(line: str):
    """Mirror the wire framing rules for a deterministic unit-level check."""
    assert line.startswith("Z")
    raw = line[1:]
    length = int(raw[:2], 16)
    assert len(raw) == 2 + length * 2
    return raw[2:4], raw[4:6], raw[6:8], raw[8:14], raw[14:20], raw[20:22], raw[22:]


class TestProtocol(unittest.TestCase):
    def test_module_is_syntax_valid(self):
        ast.parse(GATEWAY.read_text())

    def test_max_frame_decoding(self):
        # Length 0b: counter, flags, command, source, destination, group and one payload byte.
        self.assertEqual(
            parse_frame("Z0b010030abcdef1234560012"),
            ("01", "00", "30", "abcdef", "123456", "00", "12"),
        )

    def test_cul_rssi_byte_is_not_part_of_max_frame(self):
        # Received CUL MAX! frames have an extra RSSI byte when X21 is active.
        source = GATEWAY.read_text()
        self.assertIn("expected_length + 2", source)
        self.assertIn("raw = raw[:-2]", source)
        # Actual frames reported by the user have a trailing byte, e.g. ...0010C5.
        self.assertIn('rssi_raw = int(raw[-2:], 16)', source)

    def test_wall_thermostat_encoding(self):
        desired = 21.5
        measured = 20.8
        encoded_measured = int(measured * 10)
        first = ((encoded_measured & 0x100) >> 1) | (int(desired * 2) & 0x7F)
        self.assertEqual(f"{first:02x}{encoded_measured & 0xFF:02x}", "2bd0")

    def test_fhem_set_temperature_encoding(self):
        # MAX.pm: low six bits are target temperature * 2; high bits select control mode.
        target, mode = 21.5, 1  # manual
        self.assertEqual(f"{(int(target * 2) & 0x3F) | (mode << 6):02x}", "6b")

    def test_fhem_config_temperatures_encoding(self):
        # comfort, eco, max, min, offset(+3.5), window temp, duration(/5)
        payload = f"{42:02x}{34:02x}{61:02x}{9:02x}{7:02x}{24:02x}{3:02x}"
        self.assertEqual(payload, "2a223d09071803")

    def test_manifest_uses_home_assistant_serial_library(self):
        manifest = Path(__file__).parents[1] / "custom_components" / "cul_max" / "manifest.json"
        content = manifest.read_text()
        self.assertIn("pyserial-asyncio-fast", content)
        self.assertNotIn("pyserial-asyncio==0.6", content)

    def test_config_flow_uses_serializable_form_schema(self):
        flow = Path(__file__).parents[1] / "custom_components" / "cul_max" / "config_flow.py"
        source = flow.read_text()
        self.assertIn("STEP_USER_DATA_SCHEMA", source)
        self.assertIn("ConfigFlowResult", source)
        self.assertNotIn("from homeassistant.data_entry_flow import FlowResult", source)

    def test_gateway_device_is_created_before_child_devices(self):
        source = (Path(__file__).parents[1] / "custom_components" / "cul_max" / "__init__.py").read_text()
        self.assertIn("device_registry.async_get_or_create", source)
        self.assertIn("identifiers={(DOMAIN, entry.entry_id)}", source)
        self.assertIn("await hass.config_entries.async_forward_entry_setups", source)

    def test_serial_input_is_scheduled_on_home_assistant_event_loop(self):
        source = GATEWAY.read_text()
        self.assertIn("self.gateway.hass.loop.call_soon_threadsafe", source)
        self.assertIn("self.gateway.async_handle_line, line.strip()", source)

    def test_dynamic_entities_schedule_addition_on_event_loop(self):
        root = Path(__file__).parents[1] / "custom_components" / "cul_max"
        for platform in ("binary_sensor.py", "climate.py", "sensor.py"):
            source = (root / platform).read_text()
            self.assertIn("hass.add_job(async_add_entities", source)

    def test_existing_fhem_devices_are_typed_from_status_packets(self):
        source = GATEWAY.read_text()
        self.assertIn('"ThermostatState": "HeatingThermostat"', source)
        self.assertIn('"WallThermostatState": "WallMountedThermostat"', source)
        self.assertIn('"ShutterContactState": "ShutterContact"', source)
        self.assertIn('device = self._device(source, device_type)', source)

    def test_serial_handshake_waits_for_connection_made(self):
        source = GATEWAY.read_text()
        self.assertIn("self.connected = asyncio.Event()", source)
        self.assertIn("protocol = CulProtocol(self)", source)
        self.assertIn("await asyncio.wait_for(protocol.connected.wait()", source)

    def test_cul_initialisation_commands_are_present(self):
        source = GATEWAY.read_text()
        self.assertIn('CUL_RSSI_COMMAND = "X21"', source)
        self.assertIn('CUL_MAX_MODE_COMMAND = "Zr"', source)
        self.assertIn('await self._async_command("V", "V")', source)
        self.assertIn('self._write_raw(CUL_RSSI_COMMAND)', source)
        self.assertIn('self._write_raw(CUL_MAX_MODE_COMMAND)', source)
        self.assertIn('self._async_reconnect_loop()', source)


if __name__ == "__main__":
    unittest.main()
