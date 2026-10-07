#pragma once

#include <cstdint>
#include <map>
#include <vector>

#include "esphome/core/component.h"
#include "esphome/core/optional.h"
#include "esphome/core/gpio.h"
#include "esphome/core/helpers.h"
#include "esphome/components/spi/spi.h"
#include "nRF24L01.h"

namespace esphome {
namespace xiaomi_lightbar {

// Command codes (from lightbar2mqtt Lightbar::Command).
enum Command : uint8_t {
  COMMAND_ON_OFF = 0x01,
  COMMAND_COOLER = 0x02,
  COMMAND_WARMER = 0x03,
  COMMAND_BRIGHTER = 0x04,
  COMMAND_DIMMER = 0x05,
  COMMAND_RESET = 0x06,
};

// The "reset to minimum before setting an absolute value" options byte.
// In the original firmware this is (byte)(0x0 - 16) == 0xF0.
static const uint8_t OPTION_ABSOLUTE_RESET = 0xF0;

// Lightweight interface implemented by the event platform (a remote).
// Kept separate from the event header so the hub does not depend on it.
class XiaomiLightbarRemoteBase {
 public:
  virtual ~XiaomiLightbarRemoteBase() = default;
  void set_serial(uint32_t serial) { this->remote_serial_ = serial; }
  uint32_t get_serial() const { return this->remote_serial_; }
  void set_forward_to(uint32_t serial) { this->forward_to_ = serial; }
  optional<uint32_t> get_forward_to() const { return this->forward_to_; }
  // Called by the hub with a decoded (command, options) pair.
  virtual void on_command(uint8_t command, uint8_t options) = 0;

 protected:
  uint32_t remote_serial_{0};
  optional<uint32_t> forward_to_;
};

// Lightweight interface implemented by the light platform.
class XiaomiLightbarLightBase {
 public:
  virtual ~XiaomiLightbarLightBase() = default;
  void set_serial(uint32_t serial) { this->light_serial_ = serial; }
  uint32_t get_serial() const { return this->light_serial_; }
  // Flip the optimistic on/off state without transmitting anything.
  virtual void toggle_internal_state() = 0;

 protected:
  uint32_t light_serial_{0};
};

class XiaomiLightbarHub : public Component,
                         public spi::SPIDevice<spi::BIT_ORDER_MSB_FIRST, spi::CLOCK_POLARITY_LOW,
                                               spi::CLOCK_PHASE_LEADING, spi::DATA_RATE_1MHZ> {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::DATA; }

  void set_ce_pin(GPIOPin *pin) { this->ce_pin_ = pin; }
  void set_pa_level(nRF24L01::rf24_pa_dbm_e level) { this->pa_level_ = level; }
  void set_channel(uint8_t channel) { this->channel_ = channel; }
  void set_tx_repeats(uint8_t repeats) { this->tx_repeats_ = repeats; }
  void set_tx_interval(uint32_t interval_ms) { this->tx_interval_ = interval_ms; }

  void send_command(uint32_t serial, uint8_t command, uint8_t options = 0x00);

  void register_remote(XiaomiLightbarRemoteBase *remote) { this->remotes_.push_back(remote); }
  void register_light(XiaomiLightbarLightBase *light) { this->lights_.push_back(light); }
  XiaomiLightbarLightBase *get_light(uint32_t serial);

 protected:
  struct TxJob {
    uint8_t frame[17];
    uint8_t repeats_left;
  };
  struct RxState {
    bool seen{false};
    uint8_t last_seq{0};
  };

  uint8_t read_register_(uint8_t reg);
  void write_register_(uint8_t reg, uint8_t value);
  void write_register_(uint8_t reg, const uint8_t *data, uint8_t len);
  void radio_command_(uint8_t command);
  bool configure_radio_();
  bool radio_profile_ok_();
  bool read_packet_(uint8_t *packet);
  bool transmit_(const uint8_t *packet);
  uint8_t next_sequence_(uint32_t serial);
  void on_radio_data_(const uint8_t *raw, uint8_t len);
  void handle_packet_(const uint8_t *data);

  GPIOPin *ce_pin_{nullptr};
  nRF24L01::rf24_pa_dbm_e pa_level_{nRF24L01::RF24_PA_LOW};
  HighFrequencyLoopRequester high_frequency_loop_;
  uint8_t channel_{68};
  uint8_t tx_repeats_{20};
  uint32_t tx_interval_{10};

  std::vector<TxJob> tx_queue_;
  uint32_t last_tx_ms_{0};

  bool radio_ready_{false};
  uint32_t last_profile_check_ms_{0};

  std::map<uint32_t, uint8_t> tx_sequence_;
  std::map<uint32_t, RxState> rx_state_;

  std::vector<XiaomiLightbarRemoteBase *> remotes_;
  std::vector<XiaomiLightbarLightBase *> lights_;
};

}  // namespace xiaomi_lightbar
}  // namespace esphome
