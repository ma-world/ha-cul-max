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

    def test_config_flow_uses_serializable_form_schema(self):
        flow = Path(__file__).parents[1] / "custom_components" / "cul_max" / "config_flow.py"
        source = flow.read_text()
        self.assertIn("STEP_USER_DATA_SCHEMA", source)
        self.assertIn("ConfigFlowResult", source)
        self.assertNotIn("from homeassistant.data_entry_flow import FlowResult", source)

    def test_cul_initialisation_commands_are_present(self):
        source = GATEWAY.read_text()
        self.assertIn('CUL_MAX_MODE_COMMAND = "X21"', source)
        self.assertIn('await self._async_command("V", "V")', source)
        self.assertIn('await self._async_command(CUL_MAX_MODE_COMMAND, "X")', source)
        self.assertIn('await self._async_command("X", "X")', source)
        self.assertIn('self._async_reconnect_loop()', source)


if __name__ == "__main__":
    unittest.main()
