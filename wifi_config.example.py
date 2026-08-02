"""WiFi credentials for the ESP8285.

Copy this to `wifi_config.py` and fill in your own network. That file is
gitignored so the credentials stay off GitHub.

The scripts that run on the module itself (`onboard/esp_web.py`) cannot import
this - `/usr` is not on `usys.path` there - so they read `/usr/wifi.txt`
instead, two lines, SSID then password. `upload.py wifi` writes it.
"""

SSID = "YOUR_SSID"
PASSWORD = "YOUR_PASSWORD"
