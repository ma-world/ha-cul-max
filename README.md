# CUL MAX! – HACS Custom Integration

This integration ports the **gateway component** of FHEM's `14_CUL_MAX.pm` to Home Assistant. It communicates directly with a CUL or CUL-compatible USB radio stick operating in MAX! mode and processes MAX! telegrams (`Z…`) locally through the serial interface.

## Included features

- Configuration dialog for the serial port, baud rate, and MAX! addresses
- Automatic CUL initialization: firmware query, enabling the MORITZ/MAX! receiver (`Zr`), RSSI configuration (`X21`), and setting the gateway and virtual wall-thermostat addresses
- Automatic reconnection after unplugging and reconnecting the configured CUL stick (5–60 seconds with increasing retry intervals)
- Pairing mode with `PairPing` processing and `PairPong` transmission
- Reception of window-contact, wall-thermostat, and radiator-thermostat telegrams
- Dynamically created entities:
  - Window contacts as `binary_sensor`
  - Radiator and wall thermostats as `climate` entities with a target-temperature control and `Heat` / `Off` modes (`4.5 °C` represents “off” in the MAX! protocol)
  - Measured temperature, target temperature, and valve position also as `sensor` entities
- ACK/NACK evaluation and retransmission of outgoing telegrams (3 attempts, 3 seconds apart)
- Services for time synchronization, a simulated window contact, and a simulated wall thermostat

## Porting scope

In addition to the CUL gateway, the core state and control logic from FHEM's `10_MAX.pm` has been ported: decoding thermostat status telegrams, MAX! control telegrams for target temperatures, group IDs, temperature and valve configuration, plus gateway-level linking and weekly-profile packet support.

Features that depend on FHEM-specific configuration files, readings, attributes, timers, or its web interface have intentionally not been ported. Weekly profiles can already be encoded at the gateway level, but this version does not yet provide a full Home Assistant editor or persistent profile storage.

## Importing devices already paired in FHEM

In most cases, **re-pairing is not required**. MAX! devices are associated with their gateway address, not with FHEM itself.

1. Enter exactly the same six-character **`maxid`** in Home Assistant that was configured for the CUL in FHEM.
2. Stop FHEM, or otherwise ensure that FHEM no longer has the CUL open. A serial CUL stick can be used by only one system at a time.
3. Start the CUL MAX! integration. Existing devices are automatically detected from their normal status telegrams; a new `PairPing` is not required.
4. Wait for the next radio telegram, or trigger one manually:
   - Open/close a window contact or press its button.
   - Change a radiator thermostat directly on the device.
   - Change a wall thermostat directly on the device.

After the first telegram, the device appears under **Settings → Devices & services → CUL MAX!**. Radiator and wall thermostats are created as `climate` entities, while window contacts are created as `binary_sensor` entities.

> Names, weekly profiles, and other readings previously stored in FHEM are not migrated automatically. The radio pairing and device address remain intact as long as the same gateway ID is used.

## Installation through HACS

1. Add this repository to HACS as a **Custom repository** of type **Integration**.
2. Install **CUL MAX!** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and search for **CUL MAX!**.
4. Enter the CUL port, for example `/dev/ttyACM0`, and its MAX! address (`maxid`).
5. The stick must be readable and writable by Home Assistant. During startup, the integration checks the firmware and automatically enables the MAX!/MORITZ receiver and RSSI output.

> On Home Assistant OS, `/dev/serial/by-id/...` is usually more stable than `/dev/ttyACM0`.
> Use this stable device path for reliable reconnection after unplugging and reconnecting the CUL stick.
> Initialization requires CUL firmware 1.52 or later; a-culfw is also supported.

## Thermostat control in the Home Assistant UI

Radiator and wall thermostats are available as standard Home Assistant `climate`
entities. Their thermostat card supports:

- setting the target temperature from **4.5 °C to 30.5 °C** in **0.5 °C** steps;
- **Heat** mode, which sends the selected target temperature; and
- **Off** mode, which sends the MAX! off/frost-protection value of **4.5 °C**.

Switching back to **Heat** restores the previously reported target temperature. If
no target temperature has been received yet, the integration uses 20.0 °C.

## Editing weekly schedules

A graphical weekly-schedule editor is not available yet. You can write a complete
schedule for one day with the `cul_max.set_week_profile_day` action from **Developer
tools → Actions**, or use the same action in an automation/script. The action does
not currently display or import an existing schedule; it replaces the selected day
with the schedule supplied in the action data.

MAX! weekday numbers are **0 = Saturday** through **6 = Friday**. The first interval
must begin at `00:00`; every time must be a five-minute increment. A supplied
temperature stays active until the next interval, and the final one stays active
until midnight. One day accepts at most 13 intervals.

| Day | MAX! value |
| --- | --- |
| Saturday | `0` |
| Sunday | `1` |
| Monday | `2` |
| Tuesday | `3` |
| Wednesday | `4` |
| Thursday | `5` |
| Friday | `6` |

```yaml
service: cul_max.set_week_profile_day
data:
  device: "1b6ea1"
  day: 2 # Monday
  schedule:
    - time: "00:00"
      temperature: 17.0
    - time: "06:30"
      temperature: 21.0
    - time: "08:30"
      temperature: 17.0
    - time: "17:00"
      temperature: 21.0
    - time: "22:30"
      temperature: 17.0
```

Writing a weekday sends two MAX! `ConfigWeekProfile` radio packets. It is best to
change one day first and verify the thermostat has received both packets before
writing the rest of the week.

## Services

```yaml
service: cul_max.pair_mode
data:
  duration: 300
```

```yaml
service: cul_max.fake_window_contact
data:
  device: "abcdef"
  is_open: true
  group_id: 0
```

```yaml
service: cul_max.configure_temperatures
data:
  device: "abcdef"
  comfort_temperature: 21.0
  eco_temperature: 17.0
  maximum_temperature: 30.5
  minimum_temperature: 4.5
  measurement_offset: 0.0
  window_open_temperature: 12.0
  window_open_duration: 15
```

```yaml
service: cul_max.fake_wall_thermostat
data:
  device: "abcdef"
  desired_temperature: 21.5
  measured_temperature: 20.8
  group_id: 0
```

## Important notes

- MAX! uses six-character hexadecimal addresses; enter addresses without `0x`.
- Radio telegrams are transmitted directly. Test with a single device before using the integration in production.
- When multiple CUL gateways are configured, integration services currently cannot select a specific gateway. For this first version, configure only one CUL MAX! entry.
- A weekly-profile editor and reading/persisting complete device configurations are still pending. The existing gateway functions already transmit FHEM-compatible packets.

## Development

The central protocol implementation is located in `custom_components/cul_max/gateway.py`. Run protocol tests with:

```bash
python -m unittest discover -s tests -v
```
