# ESPHome Xiaomi Lightbar Proxy

One ESPHome external component for an ESP32-C3 and nRF24L01+ to control the
**Xiaomi Mi Computer Monitor Light Bar MJGJD01YL** and locally forward its stock
remote. **MJGJD02YL is not supported.**

The radio driver is built into `xiaomi_lightbar`. There is no separate `nrf24`
component, `nrf24:` YAML section, or `nrf24_id` dependency.

## Wiring

For an ESP32-C3 board that exposes these GPIOs:

| nRF24L01+ | ESP32-C3 |
| --- | --- |
| VCC | 3.3 V, never 5 V |
| GND | GND |
| CE | GPIO4 |
| CSN | GPIO10 |
| SCK | GPIO6 |
| MOSI | GPIO7 |
| MISO | GPIO5 |
| IRQ | Not connected |

Use short wires and place a 10 µF capacitor plus a 100 nF capacitor across VCC/GND
at the radio. PA/LNA modules may need a separate regulated 3.3 V supply with a
shared ground. GPIO numbers are not physical header positions.

## Configuration

See [example.yaml](example.yaml) for the complete ESP32-C3 configuration. Keep
Wi-Fi credentials in your own `secrets.yaml`; configure API encryption and OTA
authentication for your deployment.

```yaml
external_components:
  - source:
      type: git
      url: https://github.com/ShellWen/esphome-xiaomi-lightbar-proxy
      ref: main
    components: [xiaomi_lightbar]

spi:
  clk_pin: GPIO6
  mosi_pin: GPIO7
  miso_pin: GPIO5

xiaomi_lightbar:
  id: lightbar_hub
  cs_pin: GPIO10
  ce_pin: GPIO4
  data_rate: 1MHz
  pa_level: LOW

light:
  - platform: xiaomi_lightbar
    name: "Monitor Light Bar"
    xiaomi_lightbar_id: lightbar_hub
    serial: 0xABCDEF

event:
  - platform: xiaomi_lightbar
    name: "Light Bar Remote"
    xiaomi_lightbar_id: lightbar_hub
    serial: 0x123456
    forward_to: 0xABCDEF

button:
  - platform: xiaomi_lightbar
    name: "Light Bar Pair"
    xiaomi_lightbar_id: lightbar_hub
    serial: 0xABCDEF
    type: pair
```

`serial` and `forward_to` are 24-bit values. Press/turn an unconfigured remote and
look for `Action from unknown serial 0x......` in the logs to discover its serial.
Choose a different target serial and use it consistently for `forward_to`, the
light, and the pairing button. Power-cycle the lamp and press the pairing button
within its 10-second pairing window. The lamp must be paired to the proxy's
target serial, not directly to the original remote.

Forwarding runs on the ESP32 without a Home Assistant round trip. It includes
all command/options bytes, including hold/RESET, after CRC validation and
per-serial sequence deduplication. Omit `forward_to` for receive-only remote
events. The six event types are `press`, `turn_clockwise`, `turn_counterclockwise`,
`press_turn_clockwise`, `press_turn_counterclockwise`, and `hold`; corresponding
`on_<event>` triggers remain available.

The `light` supports on/off, 16 brightness steps, and color temperature. State is
optimistic: forwarded remote commands do not update the light entity's assumed
state. A button with `type: toggle_internal_state` changes the assumed on/off
state without RF transmission. `xiaomi_lightbar.send_command` still accepts
`id`, `serial`, `command`, and optional `options` for raw commands.

### Migrating from the two-component setup

1. Replace both external sources with the single source above.
2. Delete the `nrf24:` section and `xiaomi_lightbar.nrf24_id`.
3. Move `cs_pin`, `ce_pin`, `data_rate`, and `pa_level` into `xiaomi_lightbar`.
4. Remove `rf_data_rate` and `high_frequency_polling`: their behavior is built in.
5. Keep your SPI pins, entity IDs, serials, forwarding target, Wi-Fi, API, and OTA
   settings, then rebuild and flash the firmware.

### Radio behavior and tuning

The protocol is fixed to 2 Mbps, 17-byte payloads, 5-byte addresses, hardware CRC
and auto-ACK disabled, and NO_ACK transmission. Software CRC remains mandatory.
SPI uses mode 0/MSB first. High-frequency polling is active whenever the radio is
ready, with at most three received packets processed per loop. This increases
CPU activity and power consumption. Missing/reset radios are checked once per
second, and recovery restores the complete lightbar profile.

Reception resumes after **every transmitted packet**, including failed or timed
out transmissions. TX cleanup does not flush pending RX packets. The radio is
still half-duplex: packets can still be missed during the actual transmission,
RF interference, or other components blocking the ESPHome loop. NO_ACK success
means local TX completion, not confirmation from the lamp.

| Setting | Default | Meaning |
| --- | --- | --- |
| `ce_pin`, `cs_pin` | Required | Radio GPIO connections |
| `spi_id` | Auto-selected | ESPHome SPI bus, with MOSI and MISO required |
| `data_rate` | `1MHz` | SPI clock, not the fixed 2 Mbps RF rate |
| `pa_level` | `LOW` | `MIN`, `LOW`, `HIGH`, or `MAX` |
| `channel` | `68` | RF channel, 0–125; must match the lamp/remote |
| `tx_repeats` | `20` | Copies per command, 1–255 |
| `tx_interval` | `10ms` | Positive interval between TX attempts |

Keep the SPI clock within the nRF24L01+'s 10 MHz limit. Higher RF power is not
necessarily better at short range. At the default repeat count/interval, a
command occupies about 200 ms of the TX queue; rapid actions can queue up even
though reception continues between repeats. Tune repeats/interval only after
checking actual delivery on your hardware.

## Verification

```sh
python3 tests/radio_smoke.py
esphome compile example.yaml
```

The standalone check compiles and runs the actual hub and integrated driver
against a register/FIFO/CE/SPI boundary model with ASan/UBSan. It covers forwarding
during pending bursts, frame integrity, duplicate/invalid packets, sequence
rollover, TX status/failure/timeout handling, preservation of pending RX, and
radio recovery. It requires Python 3 and a C++17 compiler with sanitizer support.

This is not an RF delivery test. Physical pairing, reception loss rate, fast-turn
feel, and Wi-Fi/HA outage behavior must be checked on a real lamp and remote.

The complete ESP32-C3 example has also been compiled with ESPHome 2026.9.1 and
ESP-IDF 5.5.5, producing factory and OTA firmware images.

## Original history and licenses

Both Git histories are retained through a two-parent merge, without squashing,
rebasing, or changing the original commit IDs:

- [zweckj/esphome-xiaomi-lightbar](https://github.com/zweckj/esphome-xiaomi-lightbar),
  including the forwarding branch at
  [`b7022a8`](https://github.com/ShellWen/esphome-xiaomi-lightbar/commit/b7022a8146853449313d4d1045d4d66f034a9ed7).
- [loucks1/nrf24_espidf](https://github.com/loucks1/nrf24_espidf), including the
  driver corrections at
  [`1dfac52`](https://github.com/ShellWen/nrf24_espidf/commit/1dfac52765a2ba1603ef98f7fdd71172bfa1a25e).

The original lightbar [LICENSE](LICENSE) is preserved unchanged, including its
lightbar2mqtt attribution. The nRF24 repository has no standalone `LICENSE` file
in the imported history. Its original MIT copyright/permission notice for
Stefan Engelke and Greg Copeland is preserved verbatim in
[`nRF24L01.h`](components/xiaomi_lightbar/nRF24L01.h). This does not assert an
additional license grant for upstream files without a license notice.

The old general-purpose driver, examples, and planning files remain available
in Git history; only the dedicated lightbar component is exposed in the current
tree. Protocol credits remain with
[lightbar2mqtt](https://github.com/ebinf/lightbar2mqtt),
[lamperez](https://github.com/lamperez/xiaomi-lightbar-nrf24), and
[Ben Allen](https://github.com/benallen-dev/xiaomi-lightbar).
