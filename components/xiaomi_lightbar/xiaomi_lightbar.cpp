#include "xiaomi_lightbar.h"
#include "crc16.h"

#include <cstring>

#include "esphome/core/hal.h"
#include "esphome/core/log.h"

namespace esphome {
namespace xiaomi_lightbar {

static const char *const TAG = "xiaomi_lightbar";

// Protocol constants (verified against lightbar2mqtt radio.cpp / radio.h).
static const uint8_t PREAMBLE[8] = {0x53, 0x39, 0x14, 0xDD, 0x1C, 0x49, 0x34, 0x12};

void XiaomiLightbarHub::setup() {
  this->ce_pin_->setup();
  this->ce_pin_->digital_write(false);
  this->spi_setup();
  delay(10);
  this->radio_ready_ = this->configure_radio_();
  this->last_profile_check_ms_ = millis();
  if (this->radio_ready_)
    this->high_frequency_loop_.start();
  else
    ESP_LOGE(TAG, "nRF24 radio not responding; retrying in loop");
}

void XiaomiLightbarHub::loop() {
  const uint32_t now = millis();
  if (now - this->last_profile_check_ms_ >= 1000) {
    this->last_profile_check_ms_ = now;
    if (!this->radio_ready_ || !this->radio_profile_ok_()) {
      ESP_LOGW(TAG, "Restoring lightbar radio profile");
      this->radio_ready_ = this->configure_radio_();
    }
  }
  if (!this->radio_ready_) {
    this->high_frequency_loop_.stop();
    return;
  }
  this->high_frequency_loop_.start();

  uint8_t packet[17];
  for (uint8_t packets = 0; packets < 3 && this->read_packet_(packet); ++packets)
    this->on_radio_data_(packet, sizeof(packet));

  const uint32_t tx_now = millis();
  if (!this->tx_queue_.empty() && tx_now - this->last_tx_ms_ >= this->tx_interval_) {
    TxJob &job = this->tx_queue_.front();
    if (!this->transmit_(job.frame))
      ESP_LOGW(TAG, "Radio transmission failed");
    this->last_tx_ms_ = tx_now;
    if (--job.repeats_left == 0)
      this->tx_queue_.erase(this->tx_queue_.begin());
  }
}

void XiaomiLightbarHub::dump_config() {
  ESP_LOGCONFIG(TAG, "Xiaomi Lightbar Hub:");
  ESP_LOGCONFIG(TAG, "  Channel: %u", this->channel_);
  ESP_LOGCONFIG(TAG, "  TX repeats: %u", this->tx_repeats_);
  ESP_LOGCONFIG(TAG, "  TX interval: %u ms", this->tx_interval_);
  ESP_LOGCONFIG(TAG, "  Lights: %u, Remotes: %u", (unsigned) this->lights_.size(),
                (unsigned) this->remotes_.size());
  ESP_LOGCONFIG(TAG, "  PA level: %u", static_cast<unsigned>(this->pa_level_));
  ESP_LOGCONFIG(TAG, "  Radio ready: %s", this->radio_ready_ ? "yes" : "no");
  LOG_PIN("  CE pin: ", this->ce_pin_);
  LOG_SPI_DEVICE(this);
}



uint8_t XiaomiLightbarHub::next_sequence_(uint32_t serial) {
  uint8_t &seq = this->tx_sequence_[serial];  // value-initialized to 0 on first use
  seq++;                                       // pre-increment: first command uses 1
  return seq;
}

void XiaomiLightbarHub::send_command(uint32_t serial, uint8_t command, uint8_t options) {
  TxJob job;
  memcpy(job.frame, PREAMBLE, sizeof(PREAMBLE));
  job.frame[8] = (serial >> 16) & 0xFF;
  job.frame[9] = (serial >> 8) & 0xFF;
  job.frame[10] = serial & 0xFF;
  job.frame[11] = 0xFF;
  job.frame[12] = this->next_sequence_(serial);
  job.frame[13] = command;
  job.frame[14] = options;
  uint16_t crc = crc16_lightbar(job.frame, 15);
  job.frame[15] = (crc >> 8) & 0xFF;
  job.frame[16] = crc & 0xFF;
  job.repeats_left = this->tx_repeats_;
  if (this->tx_queue_.empty())
    this->last_tx_ms_ = millis() - this->tx_interval_;
  this->tx_queue_.push_back(job);
  ESP_LOGD(TAG, "Queued command 0x%02X (options 0x%02X) for serial 0x%06X", command, options,
           serial);
}

XiaomiLightbarLightBase *XiaomiLightbarHub::get_light(uint32_t serial) {
  for (auto *light : this->lights_) {
    if (light->get_serial() == serial)
      return light;
  }
  return nullptr;
}

void XiaomiLightbarHub::on_radio_data_(const uint8_t *raw, uint8_t len) {
  if (len < 17)
    return;
  // De-shift the raw baseband bytes back into a proper frame. See lamperez's notes:
  // https://github.com/lamperez/xiaomi-lightbar-nrf24#baseband-packet-format
  uint8_t data[17];
  data[0] = 0x50 | (raw[0] >> 5);
  for (uint8_t i = 1; i < 17; i++) {
    data[i] = static_cast<uint8_t>(((raw[i - 1] >> 1) & 0x0F) << 4) |
              static_cast<uint8_t>((raw[i - 1] & 0x01) << 3) | static_cast<uint8_t>(raw[i] >> 5);
  }
  this->handle_packet_(data);
}

void XiaomiLightbarHub::handle_packet_(const uint8_t *data) {
  if (memcmp(data, PREAMBLE, sizeof(PREAMBLE)) != 0)
    return;  // not a lightbar frame

  uint16_t calculated = crc16_lightbar(data, 15);
  uint16_t received = (static_cast<uint16_t>(data[15]) << 8) | data[16];
  if (calculated != received) {
    ESP_LOGW(TAG, "Ignoring packet with wrong checksum");
    return;
  }

  uint32_t serial = (static_cast<uint32_t>(data[8]) << 16) |
                    (static_cast<uint32_t>(data[9]) << 8) | static_cast<uint32_t>(data[10]);
  uint8_t seq = data[12];
  uint8_t command = data[13];
  uint8_t options = data[14];

  // Deduplicate: each action is transmitted ~20x with the same sequence number.
  // (The original firmware intended this but compared against the wrong field; we
  // port the intent and reject a repeat of the last sequence number per serial.)
  RxState &state = this->rx_state_[serial];
  if (state.seen && state.last_seq == seq)
    return;
  state.seen = true;
  state.last_seq = seq;

  for (auto *remote : this->remotes_) {
    if (remote->get_serial() == serial) {
      auto forward_to = remote->get_forward_to();
      if (forward_to.has_value())
        this->send_command(*forward_to, command, options);
      remote->on_command(command, options);
      return;
    }
  }
  ESP_LOGI(TAG,
           "Action from unknown serial 0x%06X (command 0x%02X). Add an 'event' with this serial "
           "to handle it.",
           serial, command);
}

}  // namespace xiaomi_lightbar
}  // namespace esphome
