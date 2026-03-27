# WiFi Remote Control

Authenticated WiFi remote control is available on ESP32 and ESP32-S3 based boards through the firmware WiFi listener in `Remote.h` and the helper at `Python Module/wifi_remote_tool.py`.

The current transport is an authenticated TCP tunnel on port `7633`. Raw WiFi control is not exposed until the client completes the challenge-response login.

## Current Capabilities

- Query device and WiFi status over USB serial.
- Provision WiFi credentials and the remote-control key over USB serial.
- Authenticate over WiFi and query device plus radio state.
- Configure LoRa radio parameters over WiFi.
- Send LoRa payloads over WiFi.
- Listen for LoRa packets over WiFi.
- Run a small set of admin operations over WiFi.

## Security Model

- WiFi control is disabled until the board is provisioned with a remote-control key.
- Provisioning happens over USB serial.
- WiFi authentication uses a device-provided nonce and device hash plus an HMAC-SHA256 response.
- The authenticated session currently gates access to the existing KISS command space.
- This is authentication, not encrypted payload tunneling yet.

## Provisioning Over USB

Set WiFi credentials, use DHCP, and install a remote-control key:

```bash
python3 'Python Module/wifi_remote_tool.py' provision <serial-port> \
  --ssid 'YourSSID' \
  --psk 'YourPassword' \
  --mode sta \
  --dhcp \
  --remote-key 'your-remote-key'
```

Check the saved WiFi state over USB:

```bash
python3 'Python Module/wifi_remote_tool.py' status <serial-port>
```

## Query Device Info Over WiFi

Once the board has joined the network and obtained an address:

```bash
python3 'Python Module/wifi_remote_tool.py' connect-info <device-ip> \
  --remote-key 'your-remote-key'
```

## Configure LoRa Over WiFi

Example using the currently validated local MeshCore profile:

```bash
python3 'Python Module/wifi_remote_tool.py' radio-config <device-ip> \
  --remote-key 'your-remote-key' \
  --freq 910525000 \
  --bw 62500 \
  --sf 7 \
  --cr 5 \
  --txp 2 \
  --radio-state on \
  --promisc
```

This prints the applied radio state back from the board.

## Send LoRa Payloads Over WiFi

Send UTF-8 text:

```bash
python3 'Python Module/wifi_remote_tool.py' send <device-ip> \
  --remote-key 'your-remote-key' \
  --text 'hello over wifi'
```

Send raw hex:

```bash
python3 'Python Module/wifi_remote_tool.py' send <device-ip> \
  --remote-key 'your-remote-key' \
  --hex '01020304aabbccdd'
```

## Listen For LoRa Packets Over WiFi

```bash
python3 'Python Module/wifi_remote_tool.py' listen <device-ip> \
  --remote-key 'your-remote-key' \
  --freq 910525000 \
  --bw 62500 \
  --sf 7 \
  --cr 5 \
  --txp 2 \
  --radio-state on \
  --promisc \
  --seconds 30
```

The listener prints packet hex, and printable text when available.

## Admin Commands Over WiFi

Persist the current radio configuration:

```bash
python3 'Python Module/wifi_remote_tool.py' admin <device-ip> \
  --remote-key 'your-remote-key' \
  --save-config
```

Other supported admin actions:

- `--reboot`
- `--bt off`
- `--bt on`
- `--bt pair`
- `--bt-unpair`
- `--display-intensity <0-255>`
- `--display-blanking <value>`
- `--display-rotation <value>`
- `--display-recondition`
- `--disable-interference-avoidance`
- `--no-disable-interference-avoidance`
- `--delete-config`

## Notes And Limitations

- The current WiFi remote path is intended for ESP32 and ESP32-S3 boards.
- The helper reconnects automatically across the brief USB bounce that happens after some WiFi config changes.
- Only one authenticated WiFi controller session is practical at a time.
- Live Heltec V4 testing showed that shorter ASCII remote-control keys were reliable. A longer 32-character secret failed authentication in testing, so prefer moderate-length ASCII keys until that edge case is resolved.
- The current implementation exposes authenticated access to KISS commands; it does not yet add role separation or payload encryption.
