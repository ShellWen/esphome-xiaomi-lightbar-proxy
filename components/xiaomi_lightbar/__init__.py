import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import automation, pins
from esphome.components import spi
from esphome.const import CONF_CHANNEL, CONF_ID

CODEOWNERS = ["@ShellWen"]
DEPENDENCIES = ["spi"]
AUTO_LOAD = ["button", "event", "light"]
MULTI_CONF = True

xiaomi_lightbar_ns = cg.esphome_ns.namespace("xiaomi_lightbar")
XiaomiLightbarHub = xiaomi_lightbar_ns.class_(
    "XiaomiLightbarHub", cg.Component, spi.SPIDevice
)
SendCommandAction = xiaomi_lightbar_ns.class_("SendCommandAction", automation.Action)

rf24_pa_dbm_e = cg.global_ns.namespace("nRF24L01").enum("rf24_pa_dbm_e")
PA_LEVELS = {
    "MIN": rf24_pa_dbm_e.RF24_PA_MIN,
    "LOW": rf24_pa_dbm_e.RF24_PA_LOW,
    "HIGH": rf24_pa_dbm_e.RF24_PA_HIGH,
    "MAX": rf24_pa_dbm_e.RF24_PA_MAX,
}

CONF_CE_PIN = "ce_pin"
CONF_PA_LEVEL = "pa_level"
CONF_TX_REPEATS = "tx_repeats"
CONF_TX_INTERVAL = "tx_interval"
CONF_XIAOMI_LIGHTBAR_ID = "xiaomi_lightbar_id"
CONF_SERIAL = "serial"
CONF_COMMAND = "command"
CONF_OPTIONS = "options"

# A light bar / remote serial is a 24-bit value, usually written like 0xABCDEF.
SERIAL_SCHEMA = cv.All(cv.hex_int, cv.Range(min=0, max=0xFFFFFF))

CONFIG_SCHEMA = spi.spi_device_schema(cs_pin_required=True).extend(
    {
        cv.GenerateID(): cv.declare_id(XiaomiLightbarHub),
        cv.Required(CONF_CE_PIN): pins.gpio_output_pin_schema,
        cv.Optional(CONF_PA_LEVEL, default="LOW"): cv.enum(PA_LEVELS, upper=True),
        cv.Optional(spi.CONF_SPI_MODE): cv.enum(
            {"MODE0": spi.SPI_MODE_OPTIONS["MODE0"]}, upper=True
        ),
        cv.Optional(CONF_CHANNEL, default=68): cv.int_range(min=0, max=125),
        cv.Optional(CONF_TX_REPEATS, default=20): cv.int_range(min=1, max=255),
        cv.Optional(
            CONF_TX_INTERVAL, default="10ms"
        ): cv.positive_time_period_milliseconds,
    }
).extend(cv.COMPONENT_SCHEMA)

FINAL_VALIDATE_SCHEMA = spi.final_validate_device_schema(
    "xiaomi_lightbar", require_mosi=True, require_miso=True
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await spi.register_spi_device(var, config)
    ce_pin = await cg.gpio_pin_expression(config[CONF_CE_PIN])
    cg.add(var.set_ce_pin(ce_pin))
    cg.add(var.set_pa_level(config[CONF_PA_LEVEL]))
    cg.add(var.set_channel(config[CONF_CHANNEL]))
    cg.add(var.set_tx_repeats(config[CONF_TX_REPEATS]))
    cg.add(var.set_tx_interval(config[CONF_TX_INTERVAL]))


SEND_COMMAND_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.use_id(XiaomiLightbarHub),
        cv.Required(CONF_SERIAL): cv.templatable(SERIAL_SCHEMA),
        cv.Required(CONF_COMMAND): cv.templatable(cv.hex_uint8_t),
        cv.Optional(CONF_OPTIONS, default=0): cv.templatable(cv.hex_uint8_t),
    }
)


@automation.register_action(
    "xiaomi_lightbar.send_command",
    SendCommandAction,
    SEND_COMMAND_SCHEMA,
    synchronous=True,
)
async def send_command_to_code(config, action_id, template_arg, args):
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    template_ = await cg.templatable(config[CONF_SERIAL], args, cg.uint32)
    cg.add(var.set_serial(template_))
    template_ = await cg.templatable(config[CONF_COMMAND], args, cg.uint8)
    cg.add(var.set_command(template_))
    template_ = await cg.templatable(config[CONF_OPTIONS], args, cg.uint8)
    cg.add(var.set_options(template_))
    return var
