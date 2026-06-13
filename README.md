# Handcryption
 
A hardware-based encrypted peer-to-peer messaging device built on MicroPython (ESP32), with a companion Flask server for speech-to-text and group chat support.
 
---
 
## Table of Contents
 
- [Overview](#overview)
- [Hardware](#hardware)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
  - [Encryption (Cencrypt)](#encryption-cencrypt)
  - [Peer-to-Peer Messaging](#peer-to-peer-messaging)
  - [Group Chat](#group-chat)
  - [Speech-to-Text](#speech-to-text)
- [Server Setup](#server-setup)
- [Device Setup](#device-setup)
- [UI & Navigation](#ui--navigation)
- [File Storage](#file-storage)

---
 
## Overview
 
Handcryption is a hardware-based encrypted peer-to-peer messaging device that runs entirely on your local network, with no cloud dependencies, designed around physical ESP32 devices. Messages are recorded via voice, transcribed using a local Vosk speech-to-text model running on a companion server, encrypted using a custom substitution cipher, and transmitted over a local TCP socket network. The device uses an e-ink display and physical buttons for all interaction — no smartphone or touchscreen required.
 
A secondary group chat feature allows multiple devices to post messages through the Flask server, which are encrypted with a shared server-side alphabet and viewable in a basic web interface.
 
---
 
## Hardware
 
| Component | Purpose |
|-----------|---------|
| ESP32 (MicroPython) | Main controller |
| SSD1680 e-ink display (250×128) | UI output via SPI |
| MAX17048 fuel gauge (I2C) | Battery percentage reading |
| Piezo buzzer (PWM) | Audio feedback chimes |
| Analog microphone (ADC pin 17) | Voice recording at 8 kHz |
| 6× push buttons | Record, Send, Select, Up, Down, Shut Off |
 
**Pin assignments:**
 
| Pin | Function |
|-----|----------|
| 5 | Record button |
| 15 | Send message button |
| 39 | Select button |
| 8 | Up button |
| 38 | Down button |
| 16 | Shut-off button |
| 14 | Buzzer (PWM) |
| 17 | Microphone (ADC) |
| 4/3 | I2C SCL/SDA (MAX17048) |
| 36/35/37 | SPI SCK/MOSI/MISO (e-ink) |
| 12/6/13/9 | E-ink DC/Busy/CS/Reset |
 
---
 
## Project Structure
 
```
handcryption/
├── main.py              # ESP32 MicroPython firmware (device code)
├── server.py            # Flask server (STT + group chat backend)
├── Cencrypt.py          # Custom substitution cipher (cipher/decipher)
├── ssd1680.py           # E-ink display driver
├── models/
│   └── vosk-model-small-en-us-0.15/   # Vosk offline STT model
├── templates/
│   └── web_msg.html     # Group chat web interface
├── known_ips.json       # Per-IP shuffled alphabet store (auto-created)
├── contacts.json        # Contact name → IP map (auto-created)
├── history.json         # Outbound message log (auto-created)
└── my_letters.json      # Client-side cipher alphabet (auto-created)
```
 
---
 
## How It Works
 
### Encryption (Cencrypt)
 
Handcryption uses [Cencrypt](https://pypi.org/project/Cencrypt/), a custom substitution cipher library available on PyPI. The full printable character set (letters, digits, punctuation, space) is stored in `LETTERS`. When two devices connect for the first time, the server shuffles a copy of `LETTERS` and sends it to the client as that device's personal cipher alphabet. This shuffled alphabet is saved to `known_ips.json` on the server and `my_letters.json` on the client, so future sessions reuse the same key.
 
- `Cencrypt.cipher(message, alphabet)` — encrypts a plaintext string using the shuffled alphabet; returns the ciphertext and the key used for that message.
- `Cencrypt.decipher(ciphertext, alphabet)` — decrypts a message given the matching alphabet.
The combined message sent over the wire is `key + ciphertext` in a single packet.
 
### Peer-to-Peer Messaging
 
The device can operate as either a **server** or a **client** in any given session:
 
**Server mode** (`esp_network_server`):
1. Connects to the home Wi-Fi network and also starts a local access point (`ESP-AP`).
2. Binds a TCP socket on port `40675` and waits for one incoming connection.
3. If the connecting IP is new, prompts the user (via voice recording) to name the contact, assigns a shuffled cipher alphabet, and sends it to the client.
4. Encrypts the queued outbound message and sends it. Saves the exchange to `history.json`.
5. Performs a liveness check every 15 seconds by verifying the client echoes its own IP back in a keep-alive packet.
**Client mode** (`esp_network_client`):
1. Connects to `ESP-AP` (the other device's access point).
2. If no alphabet is stored in `my_letters.json`, receives one from the server.
3. Waits for encrypted packets, deciphers them using the stored alphabet, plays a notification chime, and displays the message on the e-ink screen.
4. Sends a keep-alive packet (`Received <ip>`) every 15 seconds.
### Group Chat
 
The group chat feature routes through the Flask server at `192.168.1.254`:
 
1. The user sets a username (recorded by voice on first use, stored in `gc_username`).
2. Messages are posted via `POST /gc` with the username, IP, and message as query parameters.
3. The server encrypts incoming messages with a single server-side shuffled alphabet (`ALPH`) and appends them to `messg_hist`.
4. Devices can retrieve the server's alphabet via `GET /updates?Request=serv_letters` and the message history via `GET /updates?Request=prov_hist`, then decrypt locally with `Cencrypt.decipher`.
5. The web interface at `/gc` (served by `web_msg.html`) polls `GET /messages` every 2 seconds and renders the encrypted message log in a browser — messages appear encrypted to anyone intercepting the HTTP traffic.
### Speech-to-Text
 
Audio is captured at 8 kHz mono using the ADC on pin 17. While the record button is held, 16-bit PCM samples are collected in memory. On release, a WAV file is written to flash (`recording.wav`) and uploaded via `POST /stt` to the Flask server.
 
The server processes the audio with **Vosk** (offline STT, no cloud dependency) using `vosk-model-small-en-us-0.15`. The transcribed text is returned as JSON and displayed on screen for confirmation before use. A simple filler-word filter (`processing()`) strips common hesitation words (`"uh"`, `"um"`, `"hmm"`, etc.) from the result.
 
---
 
## Server Setup
 
### Requirements
 
```bash
pip install flask vosk psutil Cencrypt
```
 
Download the Vosk model and place it at `models/vosk-model-small-en-us-0.15/`:
```
https://alphacephei.com/vosk/models
```
 
### Running
 
```bash
python server.py
```
 
The server listens on `0.0.0.0:5000`. The device firmware expects it at `192.168.1.254` — update the hardcoded URL in `main.py` if your server IP differs.
 
### Endpoints
 
| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/stt` | Accepts a WAV file, returns `{"text": "..."}` |
| `GET` | `/messages` | Returns full encrypted message history as JSON |
| `GET/POST` | `/gc` | Post a group chat message or view the web UI |
| `GET` | `/updates` | Returns server alphabet or message history |
 
---
 
## Device Setup
 
1. Flash MicroPython to the ESP32.
2. Upload `main.py`, `Cencrypt.py`, and `ssd1680.py` to the device filesystem. The `Cencrypt.py` module can be downloaded from [PyPI](https://pypi.org/project/Cencrypt/) or installed via `mip` on the device.
3. Edit the Wi-Fi credentials in `main.py`:
```python
   self.wlan.connect('ssid', 'key')  # replace with your network
```
4. Update the server IP if needed (search for `192.168.1.254` in `main.py`).
5. Power on — the device displays "HANDCRYPTION" and plays the startup chime.
---
 
## UI & Navigation
 
The main menu has four options navigated with **Up/Down** and confirmed with **Select**:
 
| Icon | Option | Action |
|------|--------|--------|
| History (left) | `0` | Browse past sent messages |
| Contacts (center) | `1` | View or add contacts |
| Settings (right) | `2` | Reset data or adjust volume |
| Message bubble (top) | `3` | Access group chat |
| *(Send button)* | `4` | Record and send a direct message |
| *(Idle timeout)* | `5` | Enter client/receive mode |
 
**Button reference:**
 
| Button | Role |
|--------|------|
| Record (hold) | Capture audio |
| Send | Open send-message flow / navigate |
| Select | Confirm selection |
| Up / Down | Navigate menus |
| Shut Off (hold 1s+) | Deep sleep (wakes on release) |
 
**Battery** is drawn as a small icon in the top-right corner of every screen. The device shows a charging prompt if battery drops below 45% and blocks until it reaches 60%.
 
**Audio feedback chimes:**
- `wake_chime` — on screen wake
- `handcryption_chime` — on startup
- `notif_chime` — on message received
- `shut_off_chime` — on entering deep sleep
---
 
## File Storage
 
All JSON files are created automatically on first boot if absent.
 
| File | Contents |
|------|----------|
| `known_ips.json` | `{ "ip": [shuffled alphabet array], ... }` |
| `contacts.json` | `{ "Name": "ip", ... }` |
| `history.json` | Array of sent message records (plaintext + ciphertext + timestamp) |
| `my_letters.json` | Cipher alphabet received from server (client role only) |
| `recording.wav` | Temporary audio file, overwritten each recording |
 
The **Settings → Reset** option wipes `contacts.json`, `history.json`, and `known_ips.json` back to empty — forcing a full re-handshake and new cipher key exchange on the next connection.
 
---
