import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

SUPPORT = r'''
#pragma once
#include <array>
#include <cstdint>
#include <deque>
#include <functional>
#include <optional>
#include <string>
#include <vector>
#define BIT(n) (1U << (n))
#define ESPHOME_LOG_LEVEL 0
#define ESPHOME_LOG_LEVEL_VERBOSE 5
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
#define ESP_LOGV(...) ((void)0)
#define ESP_LOGCONFIG(...) ((void)0)
#define LOG_PIN(...) ((void)0)
#define LOG_SPI_DEVICE(...) ((void)0)
namespace hardware {
inline uint64_t us = 0;
inline bool features_locked = false;
inline std::array<uint8_t, 32> reg{};
inline std::array<std::array<uint8_t, 5>, 32> addresses{};
inline std::deque<std::array<uint8_t, 17>> rx;
inline std::vector<std::array<uint8_t, 17>> sent;
inline std::array<uint8_t, 17> payload{};
inline bool ce = false, queued = false, pending = false, first = true;
inline uint8_t command = 0, outcome = 0x20;
inline unsigned offset = 0;
inline uint64_t completion = 0;
inline void update() {
  if (pending && outcome && us >= completion) {
    pending = false;
    reg[7] |= outcome;
    if (outcome == 0x20) { sent.push_back(payload); queued = false; }
  }
}
inline uint8_t status() {
  update();
  return (reg[7] & 0x70) | (rx.empty() ? 0x0E : 0);
}
inline void set_ce(bool value) {
  if (value && !ce && (reg[0] & 3) == 2 && queued
      && addresses[0x10] == std::array<uint8_t, 5>{0x55, 0x55, 0x55, 0x55, 0x55}) {
    pending = true;
    completion = us + 222;
  }
  ce = value;
}
inline bool receiving() {
  return ce && reg[0] == 3 && reg[1] == 0 && (reg[2] & 1) && reg[0x11] == 17
         && (reg[6] & 0x28) == 8 && addresses[0x0A] == std::array<uint8_t, 5>{0xAA, 0xAA, 0xAA, 0xAA, 0xAA};
}
inline bool receive(const std::array<uint8_t, 17> &frame) {
  if (!receiving() || rx.size() == 3) return false;
  rx.push_back(frame);
  reg[7] |= 0x40;
  return true;
}
inline uint8_t transfer(uint8_t value) {
  us += 2;
  update();
  if (first) {
    first = false; command = value; offset = 0;
    if (command == 0xE1) { queued = false; pending = false; }
    if (command == 0xE2) rx.clear();
    return status();
  }
  unsigned index = offset++;
  if (command < 0x20) {
    if (command == 7) return status();
    if (command == 0x17) return (queued ? 0 : 0x10) | (rx.empty() ? 1 : 0);
    return reg[command];
  }
  if (command < 0x40) {
    if (index < 5) addresses[command & 31][index] = value;
    if (index == 0) {
      if ((command & 31) == 7) reg[7] &= ~(value & 0x70);
      else if ((command & 31) != 0x1D || !features_locked) reg[command & 31] = value;
    }
  } else if (command == 0x50 && value == 0x73) {
    features_locked = !features_locked;
  } else if (command == 0x61 && !rx.empty()) {
    return rx.front().at(index);
  } else if ((command == 0xA0 || command == 0xB0) && index < payload.size()) {
    payload[index] = value;
  }
  return status();
}
inline void end() {
  if (command == 0x61 && !rx.empty()) rx.pop_front();
  if (command == 0xA0 || (command == 0xB0 && (reg[0x1D] & 1))) queued = true;
}
inline void reset() {
  us = 0; reg.fill(0); reg[0] = 0x0C; reg[3] = 3;
  rx.clear(); sent.clear(); payload.fill(0); addresses = {};
  ce = queued = pending = false; first = true; outcome = 0x20;
  features_locked = false;
}
}
inline void esp_rom_delay_us(uint32_t us) { hardware::us += us; hardware::update(); }
namespace esphome {
inline uint32_t millis() { return uint32_t(hardware::us / 1000); }
inline void delay(uint32_t ms) { esp_rom_delay_us(ms * 1000); }
inline void delayMicroseconds(uint32_t us) { esp_rom_delay_us(us); }
inline void yield() { esp_rom_delay_us(100); }
template<class T> using optional = std::optional<T>;
namespace setup_priority { inline constexpr float DATA = 600; }
class Component {
 public:
  virtual ~Component() = default;
  virtual void setup() {}
  virtual void loop() {}
  virtual void dump_config() {}
  virtual float get_setup_priority() const { return 0; }
  void mark_failed() {}
};
class HighFrequencyLoopRequester {
 public:
  void start() { active = true; }
  void stop() { active = false; }
  inline static bool active = false;
};
class GPIOPin {
 public:
  void setup() {}
  void digital_write(bool value) { hardware::set_ce(value); }
};
namespace spi {
enum { BIT_ORDER_MSB_FIRST, CLOCK_POLARITY_LOW, CLOCK_PHASE_LEADING, DATA_RATE_1MHZ };
template<int, int, int, int> class SPIDevice {
 public:
  void spi_setup() {}
  void enable() { hardware::first = true; }
  void disable() { hardware::end(); }
  uint8_t transfer_byte(uint8_t value) { return hardware::transfer(value); }
  void read_array(uint8_t *data, unsigned len) { for (unsigned i=0; i<len; ++i) data[i]=transfer_byte(0xFF); }
  void write_array(const uint8_t *data, unsigned len) { for (unsigned i=0; i<len; ++i) transfer_byte(data[i]); }
};
}
}
'''

CHECK = r'''
#include "esphome/components/xiaomi_lightbar/xiaomi_lightbar.h"
#include "esphome/components/xiaomi_lightbar/crc16.h"
#include <cassert>
#include <cstdio>
using namespace esphome;
using namespace esphome::xiaomi_lightbar;
void check(bool ok, const char *name) {
  std::printf("%s: %s\n", ok ? "PASS" : "FAIL", name);
  assert(ok);
}
std::array<uint8_t, 17> frame(uint8_t sequence, uint8_t command) {
  std::array<uint8_t, 17> data{0x53, 0x39, 0x14, 0xDD, 0x1C, 0x49, 0x34, 0x12,
                              0x22, 0x44, 0x11, 0xFF, sequence, command, 1};
  auto crc = crc16_lightbar(data.data(), 15);
  data[15] = crc >> 8; data[16] = crc;
  std::array<uint8_t, 17> raw{};
  for (unsigned i=0; i<raw.size(); ++i)
    raw[i] = (data[i] << 5) | (i+1 < data.size() ? data[i+1] >> 3 : 0);
  return raw;
}
struct Remote : XiaomiLightbarRemoteBase {
  std::vector<uint8_t> commands;
  void on_command(uint8_t command, uint8_t) override { commands.push_back(command); }
};
struct Hub : XiaomiLightbarHub { using XiaomiLightbarHub::transmit_; };
int main() {
  hardware::reset();
  hardware::features_locked = true;
  hardware::reg[7] = 0x70;
  GPIOPin pin;
  Hub hub;
  Remote remote;
  remote.set_serial(0x224411); remote.set_forward_to(0xAF430C);
  hub.set_ce_pin(&pin); hub.register_remote(&remote); hub.setup();
  check(hardware::receiving() && (hardware::reg[7] & 0x70) == 0
        && !hardware::features_locked && HighFrequencyLoopRequester::active,
        "boot unlocks NO_ACK and enters high-frequency lightbar RX");

  hardware::receive(frame(1, 1)); hardware::receive(frame(2, 4)); hardware::receive(frame(3, 5));
  hub.loop();
  check(remote.commands == std::vector<uint8_t>({1, 4, 5}) && hardware::rx.empty(),
        "one loop delivers all three queued valid commands");
  check(hardware::sent.size() == 1 && hardware::receiving(), "RX resumes after the first TX repeat");
  auto corrupt = frame(4, 2); corrupt[13] ^= 0x20;
  auto foreign = frame(4, 2); foreign[0] ^= 0x20;
  hardware::receive(frame(3, 5)); hardware::receive(corrupt); hardware::receive(foreign);
  hub.loop();
  check(remote.commands == std::vector<uint8_t>({1, 4, 5}), "duplicates, bad CRC and wrong preamble are ignored");
  bool accepted = hardware::receive(frame(4, 2));
  hub.loop();
  check(accepted && remote.commands == std::vector<uint8_t>({1, 4, 5, 2}),
        "new remote action arrives while the previous TX burst is pending");
  for (unsigned i=0; i<1000; ++i) { delay(1); hub.loop(); }
  bool valid = hardware::sent.size() == 80;
  for (unsigned i=0; i<hardware::sent.size(); ++i) {
    const auto &data = hardware::sent[i];
    auto crc = crc16_lightbar(data.data(), 15);
    valid &= data[8] == 0xAF && data[9] == 0x43 && data[10] == 0x0C
             && data[12] == i/20+1 && data[13] == remote.commands.at(i/20)
             && data[14] == 1 && data[15] == (crc >> 8) && data[16] == (crc & 255);
  }
  check(valid && hardware::receiving(), "forwarding preserves target, command, options, order, CRC and 20 repeats");

  const auto payload = hardware::sent.front();
  hardware::receive(frame(5, 6));
  hardware::reg[7] |= 0x30;
  auto started = hardware::us;
  auto previous = hardware::sent.size();
  check(hub.transmit_(payload.data()) && hardware::sent.size() == previous+1 && hardware::us-started < 5000,
        "stale TX flags and unread RX cannot cause premature TX completion");
  check(hardware::receiving() && hardware::rx.size() == 1 && (hardware::reg[7] & 0x70) == 0x40,
        "TX preserves pending RX payload and RX interrupt");
  hardware::outcome = 0x10;
  check(!hub.transmit_(payload.data()) && !hardware::queued && hardware::receiving() && hardware::rx.size() == 1,
        "MAX_RT discards unsent TX and resumes RX without flushing it");
  hardware::outcome = 0;
  hardware::us = (uint64_t(UINT32_MAX)-30) * 1000;
  started = hardware::us;
  check(!hub.transmit_(payload.data()) && hardware::us-started >= 95000 && hardware::us-started < 100000
        && !hardware::queued && hardware::receiving() && hardware::rx.size() == 1,
        "TX timeout survives millis rollover and restores RX");
  hardware::outcome = 0x20;
  hub.loop();
  check(remote.commands == std::vector<uint8_t>({1, 4, 5, 2, 6}), "pending RESET is delivered after failed TX");
  for (unsigned i=0; i<1000; ++i) { delay(1); hub.loop(); }

  hub.set_tx_repeats(1);
  previous = hardware::sent.size();
  for (unsigned i=0; i<256; ++i) {
    hub.send_command(0x010203, 4, 3); hub.loop(); delay(10);
  }
  valid = hardware::sent.size() == previous+256;
  for (unsigned i=0; i<256; ++i) {
    const auto &data = hardware::sent.at(previous+i);
    auto crc = crc16_lightbar(data.data(), 15);
    valid &= data[8] == 1 && data[9] == 2 && data[10] == 3 && data[12] == uint8_t(i+1)
             && data[13] == 4 && data[14] == 3 && data[15] == (crc >> 8) && data[16] == (crc & 255);
  }
  check(valid, "independent target sequence wraps from 255 to zero with valid CRC");
  hardware::receive(frame(255, 3)); hub.loop();
  hardware::receive(frame(0, 4)); hub.loop();
  hardware::receive(frame(0, 4)); hub.loop();
  check(remote.commands == std::vector<uint8_t>({1, 4, 5, 2, 6, 3, 4}), "RX sequence rollover does not discard a new action");

  hardware::reg[3] = 0xFF;
  delay(1001); hub.loop();
  check(!hardware::ce && !HighFrequencyLoopRequester::active, "unavailable radio releases high-frequency polling");
  auto clock = hardware::us;
  hardware::reset(); hardware::us = clock;
  delay(1001); hub.loop();
  check(hardware::receiving() && HighFrequencyLoopRequester::active, "radio recovery reapplies the complete lightbar profile");
  hardware::receive(frame(1, 1)); hub.loop();
  check(remote.commands == std::vector<uint8_t>({1, 4, 5, 2, 6, 3, 4, 1}), "commands are received again after radio recovery");
}
'''

with tempfile.TemporaryDirectory(prefix="lightbar-radio-smoke-") as directory:
    temporary = Path(directory)
    (temporary / "support.h").write_text(SUPPORT)
    for header in ("core/component.h", "core/gpio.h", "core/helpers.h", "core/hal.h", "core/log.h", "core/optional.h", "components/spi/spi.h"):
        target = temporary / "esphome" / header
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('#include "support.h"\n')
    (temporary / "esphome/components/xiaomi_lightbar").symlink_to(ROOT / "components/xiaomi_lightbar")
    source = temporary / "smoke.cpp"
    source.write_text(CHECK)
    executable = temporary / "smoke"
    component = ROOT / "components/xiaomi_lightbar"
    subprocess.run([os.environ.get("CXX", "c++"), "-std=c++17", "-O1", "-g", "-fsanitize=address,undefined", "-I", str(temporary), str(source), str(component / "nrf24.cpp"), str(component / "xiaomi_lightbar.cpp"), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True, timeout=10)
