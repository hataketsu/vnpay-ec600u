"""EC600U GPIO metadata, from Quectel's QuecPython GPIO configuration sheet
and the hardware design manual, plus what was measured on this board.

Fields per GPIO: module pin, the pin's default function, its power domain,
the module-level signal name where one exists, and any note worth seeing
before driving it.
"""

# gpio: (module_pin, default_function, power_domain, module_signal)
PINS = {
    1:  (61,  "i2s2_bck",        "1V8",     ""),
    2:  (58,  "i2s2_lrck",       "1V8",     ""),
    3:  (34,  "uart_2_rts",      "1V8",     ""),
    4:  (60,  "i2s2_sdat_o",     "1V8",     ""),
    5:  (69,  "gpio_5",          "1V8",     ""),
    6:  (70,  "gpio_6",          "1V8",     ""),
    7:  (123, "uart_1_rxd",      "1V8",     "UART2_RXD"),
    8:  (118, "sdmmc2_clk",      "1V8_RTC", ""),
    9:  (9,   "gpio_9",          "1V8_RTC", ""),
    10: (1,   "spi_0_clk",       "1V8_RTC", "SPI_CLK"),
    11: (4,   "spi_0_cs",        "1V8_RTC", "SPI_CS"),
    12: (3,   "spi_0_dio",       "1V8_RTC", "SPI_TXD"),
    13: (2,   "spi_0_di",        "1V8_RTC", "SPI_RXD"),
    14: (54,  "gpio_14",         "1V8",     "NET_STATUS"),
    15: (57,  "i2c_1_scl",       "1V8",     ""),
    16: (56,  "i2c_1_sda",       "1V8",     ""),
    17: (12,  "i2c_0_sda",       "1V8",     ""),
    18: (33,  "uart_2_cts",      "1V8",     ""),
    19: (124, "uart_1_txd",      "1V8",     "UART2_TXD"),
    20: (122, "uart_1_rts",      "1V8",     ""),
    21: (121, "uart_1_cts",      "1V8",     ""),
    22: (48,  "sdmmc1_cmd",      "V_MMC",   "MAIN_DCD"),
    23: (39,  "sdmmc1_data_0",   "V_MMC",   "MAIN_DTR"),
    24: (40,  "sdmmc1_data_1",   "V_MMC",   "MAIN_RI"),
    25: (49,  "sdmmc1_data_2",   "V_MMC",   "WAKEUP_IN"),
    26: (50,  "sdmmc1_data_3",   "V_MMC",   "AP_READY"),
    27: (53,  "sim_2_clk",       "V_SIM2",  ""),
    28: (52,  "sim_2_dio",       "V_SIM2",  ""),
    29: (51,  "sim_2_rst",       "V_SIM2",  ""),
    30: (59,  "i2s2_sdat_i",     "1V8",     ""),
    31: (66,  "spi_lcd_sio",     "V_LCD",   ""),
    32: (63,  "spi_lcd_sdc",     "V_LCD",   ""),
    33: (67,  "spi_lcd_clk",     "V_LCD",   ""),
    34: (65,  "spi_lcd_cs",      "V_LCD",   ""),
    35: (137, "spi_lcd_select",  "V_LCD",   ""),
    36: (62,  "lcd_fmark",       "V_LCD",   ""),
    37: (98,  "sdmmc2_data_0",   "1V8_RTC", ""),
    38: (95,  "sdmmc2_data_1",   "1V8_RTC", ""),
    39: (119, "sdmmc2_data_2",   "1V8_RTC", ""),
    40: (100, "sdmmc2_data_3",   "1V8_RTC", ""),
    41: (120, "camera_rst_l",    "1V8",     ""),
    42: (16,  "camera_pwdn",     "1V8",     ""),
    43: (10,  "camera_ref_clk",  "1V8",     ""),
    44: (14,  "spi_camera_si_0", "1V8",     ""),
    45: (15,  "spi_camera_si_1", "1V8",     ""),
    46: (13,  "spi_camera_sck",  "1V8",     ""),
    47: (99,  "sdmmc2_cmd",      "1V8_RTC", ""),
}

# Measured on this board with every pin held high-impedance, nothing pressed.
# GPIO41 has read HIGH, then LOW, then HIGH across captures - it moves, so do
# not treat it as fixed.
EXTERNALLY_DRIVEN = {2: "HIGH", 23: "LOW", 24: "LOW", 35: "LOW",
                     36: "LOW", 40: "HIGH", 41: "HIGH?"}

ESP_STRAP = 26       # module pin 50, AP_READY - LOW lets the ESP flash-boot
NOR_SPI = (1, 2, 4, 30)   # SPI1 to the 16 MB NOR; GPIO2 is its chip select
# Sound was heard while sweeping this group, so the HT8313 shutdown pin is
# one of them. Narrow it with pa_pin_hunt.py.
PA_CANDIDATES = (5, 6, 8, 9, 15, 16, 17, 18)

ESP_EN = 44          # module pin 14 - drives the ESP8285 enable, active high
ESP_UART = "UART2"   # module pins 31/32 -> ESP UART0

BUTTONS = {28: "M", 27: "+", 16: "-"}   # active HIGH: pressed = driven high
LEDS = {15: "red"}                      # active HIGH: driving it high lights it

NOTES = {
    28: ("BUTTON M", "Button M. Active HIGH - pressed drives it high, released "
                     "floats. Read it with PULL_PD."),
    27: ("BUTTON +", "Button +. Active HIGH, same as M. Read with PULL_PD."),
    16: ("BUTTON -", "Button -. Active HIGH. Also one of the pins that was "
                     "live when sound was first heard, so it may double as the "
                     "amplifier shutdown line - check before driving it."),
    26: ("ESP BOOT STRAP", "Module pin 50, AP_READY. Hold LOW and the ESP "
                           "flash-boots; high or floating and it lands in UART "
                           "download mode."),
    2:  ("NOR CS", "SPI1 chip select for the 16 MB NOR. Reads high because of "
                   "its pull-up. The chip stopped answering after an "
                   "interrupted erase."),
    1:  ("NOR bus", "SPI1 clock to the NOR flash."),
    4:  ("NOR bus", "SPI1 data to the NOR flash."),
    30: ("NOR bus", "SPI1 data to the NOR flash."),
    44: ("ESP ENABLE", "Drives the ESP8285 enable, active HIGH. Found by "
                       "sweeping every pin; the only one that produced life "
                       "on UART2."),
    14: ("KILLS ESP", "Driving this HIGH silences the ESP completely (zero "
                      "bytes). Keep it LOW. Default function is the network "
                      "status LED."),
    7:  ("uart", "Module UART2 RX (pin 123). Reads as floating - nothing "
                 "wired to it on this board."),
    19: ("uart", "Module UART2 TX (pin 124). Outputs log by default; unstable "
                 "at power-on, unsuitable for power enable."),
    20: ("uart", "Outputs log by default; unstable at power-on."),
    21: ("uart", "Outputs log by default; unstable at power-on."),
    43: ("unstable", "Outputs a clock by default; unstable at power-on."),
    47: ("boot-high", "High at power-on, driven low by software ~2 s later."),
    37: ("boot-high", "High at power-on, driven low by software ~2 s later."),
    39: ("boot-high", "High at power-on, driven low by software ~2 s later."),
    42: ("boot-high", "High at power-on, driven low by software ~2 s later."),
    46: ("boot-high", "High at power-on, driven low by software ~2 s later."),
    17: ("boot-high", "High at power-on, driven low by software ~2 s later."),
    5:  ("audio?", "In the group that was live when sound was first heard."),
    6:  ("audio?", "In the group that was live when sound was first heard."),
    8:  ("audio?", "In the group that was live when sound was first heard."),
    9:  ("audio?", "In the group that was live when sound was first heard."),
    15: ("LED red", "Lights the red LED when driven HIGH. Module pin 57, "
                    "default function i2c_1_scl. Also sat in the group that "
                    "was live when sound was first heard, so that grouping no "
                    "longer implicates it in the audio path."),
    18: ("audio?", "In the group that was live when sound was first heard."),
}

# GPIOs that share a pad with another GPIO - only one of the pair can be
# configured at a time.
CONFLICTS = {1: 31, 31: 1, 2: 32, 32: 2, 30: 33, 33: 30, 4: 34, 34: 4,
             5: 35, 35: 5, 6: 36, 36: 6, 9: 47, 47: 9, 10: 37, 37: 10,
             11: 38, 38: 11, 12: 39, 39: 12, 13: 40, 40: 13, 3: 41, 41: 3,
             18: 42, 42: 18, 7: 43, 43: 7, 19: 44, 44: 19, 20: 45, 45: 20,
             21: 46, 46: 21}
