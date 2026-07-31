# CUL MAX! – HACS Custom Integration

Diese Integration portiert den **Gateway-Teil** von FHEMs `14_CUL_MAX.pm` nach Home Assistant. Sie kommuniziert direkt mit einem CUL-/CUL-kompatiblen USB-Funkstick, der im MAX!-Modus arbeitet, und verarbeitet MAX!-Telegramme (`Z…`) lokal über die serielle Schnittstelle.

## Enthaltene Funktionen

- Konfigurationsdialog für seriellen Port, Baudrate und MAX!-Adressen
- Automatische CUL-Initialisierung: Firmware-Abfrage, Aktivierung des
  MORITZ/MAX!-Empfangs (`Zr`), RSSI-Konfiguration (`X21`) sowie Setzen der Gateway-
  und Fake-Wandthermostat-Adresse
- Automatische Wiederverbindung nach Aus-/Einstecken des konfigurierten CUL-Sticks
  (5–60 Sekunden, steigende Wartezeit)
- Anlernmodus mit Verarbeitung von `PairPing` und Versand von `PairPong`
- Empfang von Fensterkontakt-, Wandthermostat- und Heizkörperthermostat-Telegrammen
- Dynamisch angelegte Entitäten:
  - Fensterkontakte als `binary_sensor`
  - Heiz- und Wandthermostate als `climate`-Entität mit Solltemperatur und Ein/Aus
  (4,5 °C entspricht „aus“ im MAX!-Protokoll)
- gemessene Temperatur, Solltemperatur und Ventilstellung zusätzlich als `sensor`
- ACK/NACK-Auswertung sowie Wiederholung ausgehender Telegramme (3 Versuche, je 3 Sekunden)
- Dienste für Zeitsynchronisation, simulierten Fensterkontakt und simuliertes Wandthermostat

## Portierungsumfang

Zusätzlich zum CUL-Gateway ist die wesentliche Zustands- und Steuerlogik aus FHEMs `10_MAX.pm` übernommen: Dekodierung der Thermostatstatus-Telegramme, MAX!-Steuertelegramme für Solltemperatur, Gruppen-IDs, Temperatur- und Ventilkonfiguration sowie Verknüpfungs- und Wochenprofil-Paketfunktionen auf Gateway-Ebene.

Die Funktionen, die FHEM-spezifische Konfigurationsdateien, Readings, Attribute, Timer oder dessen Weboberfläche benötigen, wurden bewusst nicht übernommen. Die Week-Profile sind bereits im Gateway kodierbar, haben aber in dieser Version noch keinen vollwertigen Home-Assistant-Editor bzw. keinen persistenten Profil-Speicher.

## Installation über HACS

1. Dieses Repository in HACS als **Custom repository** vom Typ **Integration** hinzufügen.
2. **CUL MAX!** installieren und Home Assistant neu starten.
3. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **CUL MAX!** suchen.
4. Den Port des CUL eintragen, z. B. `/dev/ttyACM0`, sowie dessen MAX!-Adresse (`maxid`).
5. Der Stick muss für Home Assistant les- und schreibbar sein. Die Integration prüft beim Start die Firmware,
   aktiviert automatisch den MAX!/MORITZ-Empfang sowie die RSSI-Ausgabe.

> Bei Home Assistant OS ist der Host-Port üblicherweise als `/dev/serial/by-id/...` stabiler als `/dev/ttyACM0`.
> Verwende diese stabile Geräteadresse auch für die automatische Wiederverbindung nach einem Aus-/Einstecken.
> Für die Initialisierung wird mindestens CUL-Firmware 1.52 benötigt; a-culfw wird ebenfalls akzeptiert.

## Dienste

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

## Wichtige Hinweise

- MAX! verwendet 6-stellige Hexadressen; die Adressen werden ohne `0x` eingegeben.
- Funktelegramme werden direkt gesendet. Vor produktivem Einsatz mit einem einzelnen Gerät testen.
- Mehrere konfigurierte CUL-Gateways werden derzeit noch nicht per Dienst auswählbar unterstützt. Für die erste Version bitte genau einen CUL MAX!-Eintrag verwenden.
- Ein Wochenprofil-Editor und das Auslesen/Persistieren kompletter Geräte-Konfigurationen sind noch offen. Die vorhandenen Gateway-Funktionen senden aber bereits die FHEM-kompatiblen Pakete.

## Entwicklung

Die zentrale Protokollimplementierung liegt in `custom_components/cul_max/gateway.py`. Parser-Tests lassen sich mit `python -m unittest discover -s tests -v` ausführen.
