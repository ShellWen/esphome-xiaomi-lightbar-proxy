#include "xiaomi_lightbar.h"

#include "esphome/core/hal.h"

namespace esphome {
namespace xiaomi_lightbar {

using namespace nRF24L01;

static const uint8_t SEND_ADDRESS[5] = {0x55, 0x55, 0x55, 0x55, 0x55};
static const uint8_t RECEIVE_ADDRESS[5] = {0xAA, 0xAA, 0xAA, 0xAA, 0xAA};

uint8_t XiaomiLightbarHub::read_register_(uint8_t reg) {
  this->enable();
  this->transfer_byte(R_REGISTER | (reg & REGISTER_MASK));
  uint8_t value = this->transfer_byte(NOP);
  this->disable();
  return value;
}

void XiaomiLightbarHub::write_register_(uint8_t reg, uint8_t value) {
  this->enable();
  this->transfer_byte(W_REGISTER | (reg & REGISTER_MASK));
  this->transfer_byte(value);
  this->disable();
}

void XiaomiLightbarHub::write_register_(uint8_t reg, const uint8_t *data, uint8_t len) {
  this->enable();
  this->transfer_byte(W_REGISTER | (reg & REGISTER_MASK));
  this->write_array(data, len);
  this->disable();
}

void XiaomiLightbarHub::radio_command_(uint8_t command) {
  this->enable();
  this->transfer_byte(command);
  this->disable();
}

bool XiaomiLightbarHub::configure_radio_() {
  this->ce_pin_->digital_write(false);
  const uint8_t address_width = this->read_register_(SETUP_AW);
  if (address_width < 1 || address_width > 3)
    return false;

  this->write_register_(CONFIG, 0);
  delay(10);
  this->write_register_(EN_AA, 0);
  this->write_register_(EN_RXADDR, 1);
  this->write_register_(SETUP_AW, 3);
  this->write_register_(SETUP_RETR, 0);
  this->write_register_(RF_CH, this->channel_);
  this->write_register_(RF_SETUP, (1U << RF_DR_HIGH) | (this->pa_level_ << 1) | 1U);
  delayMicroseconds(200);
  this->write_register_(FEATURE, 1U << EN_DYN_ACK);
  if (this->read_register_(FEATURE) != (1U << EN_DYN_ACK)) {
    this->enable();
    this->transfer_byte(ACTIVATE);
    this->transfer_byte(0x73);
    this->disable();
    this->write_register_(FEATURE, 1U << EN_DYN_ACK);
  }
  this->write_register_(DYNPD, 0);
  this->write_register_(RX_PW_P0, 17);
  this->write_register_(TX_ADDR, SEND_ADDRESS, sizeof(SEND_ADDRESS));
  this->write_register_(RX_ADDR_P0, RECEIVE_ADDRESS, sizeof(RECEIVE_ADDRESS));
  this->radio_command_(FLUSH_RX);
  this->radio_command_(FLUSH_TX);
  this->write_register_(STATUS, RF24_IRQ_ALL);
  this->write_register_(CONFIG, (1U << PWR_UP) | (1U << PRIM_RX));
  delay(5);
  if (!this->radio_profile_ok_())
    return false;
  this->ce_pin_->digital_write(true);
  delayMicroseconds(130);
  return true;
}

bool XiaomiLightbarHub::radio_profile_ok_() {
  return this->read_register_(CONFIG) == ((1U << PWR_UP) | (1U << PRIM_RX)) &&
         this->read_register_(SETUP_AW) == 3 && this->read_register_(RF_CH) == this->channel_ &&
         this->read_register_(RF_SETUP) == ((1U << RF_DR_HIGH) | (this->pa_level_ << 1) | 1U) &&
         this->read_register_(EN_AA) == 0 && this->read_register_(EN_RXADDR) == 1 &&
         this->read_register_(RX_PW_P0) == 17 && this->read_register_(DYNPD) == 0 &&
         this->read_register_(FEATURE) == (1U << EN_DYN_ACK);
}

bool XiaomiLightbarHub::read_packet_(uint8_t *packet) {
  if (this->read_register_(FIFO_STATUS) & (1U << RX_EMPTY))
    return false;
  this->enable();
  this->transfer_byte(R_RX_PAYLOAD);
  this->read_array(packet, 17);
  this->disable();
  this->write_register_(STATUS, RF24_RX_DR);
  return true;
}

bool XiaomiLightbarHub::transmit_(const uint8_t *packet) {
  this->ce_pin_->digital_write(false);
  this->write_register_(CONFIG, 1U << PWR_UP);
  this->write_register_(STATUS, RF24_TX_DS | RF24_TX_DF);
  this->enable();
  this->transfer_byte(W_TX_PAYLOAD_NO_ACK);
  this->write_array(packet, 17);
  this->disable();
  this->ce_pin_->digital_write(true);
  delayMicroseconds(130);

  const uint32_t started = millis();
  uint8_t status;
  while (!((status = this->read_register_(STATUS)) & (RF24_TX_DS | RF24_TX_DF))) {
    if (millis() - started >= 95)
      break;
    yield();
  }
  this->ce_pin_->digital_write(false);
  this->write_register_(STATUS, RF24_TX_DS | RF24_TX_DF);
  const bool sent = (status & (RF24_TX_DS | RF24_TX_DF)) == RF24_TX_DS;
  if (!sent)
    this->radio_command_(FLUSH_TX);
  this->write_register_(CONFIG, (1U << PWR_UP) | (1U << PRIM_RX));
  this->ce_pin_->digital_write(true);
  delayMicroseconds(130);
  return sent;
}

}  // namespace xiaomi_lightbar
}  // namespace esphome
