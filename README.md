# Handcryption
 
A hardware-based encrypted peer-to-peer messaging device built on MicroPython (ESP32), with a companion Flask server for speech-to-text, message relay, and group chat support.
 
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
 
Handcryption is a hardware-based encrypted peer-to-peer messaging device built around physical ESP32 devices and a Flask server hosted on a Raspberry Pi 4, exposed publicly via an ngrok tunnel. Messages are recorded via voice, transcribed using a local Vosk speech-to-text model on the companion server, encrypted using a custom substitution cipher, and relayed through the server's mailbox system. The device uses an e-ink display and physical buttons for all interaction — no smartphone or touchscreen required.
 
Each device is assigned a unique numeric ID on first boot, which is used to route messages and identify contacts. A secondary group chat feature allows multiple devices to post to a shared encrypted channel viewable in a basic web interface.
 
---
 
## Hardware
 
| Component | Purpose |
|-----------|---------|
| Adafruit ESP32-S2 Feather (MicroPython) | Main controller |
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
├── server.py            # Flask server (STT + relay + group chat backend)
├── Cencrypt.py          # Custom substitution cipher (cipher/decipher)
├── ssd1680.py           # E-ink display driver
├── models/
│   └── vosk-model-small-en-us-0.15/   # Vosk offline STT model
├── templates/
│   └── web_msg.html     # Group chat web interface
├── known_ids.json       # Per-device-ID shuffled alphabet store (auto-created)
├── contacts.json        # Contact name → device ID map (auto-created)
├── history.json         # Outbound message log (auto-created)
├── my_letters.json      # Client-side cipher alphabet (auto-created)
└── device_ID.json       # This device's unique ID (auto-created on first boot)
```
 
---
 
## How It Works
 
### Encryption (Cencrypt)
 
Handcryption uses [Cencrypt](https://pypi.org/project/Cencrypt/), a custom substitution cipher library available on PyPI. The full printable character set (letters, digits, punctuation, space) is stored in `LETTERS`. When two devices connect for the first time, the sending device shuffles a copy of `LETTERS` and sends it to the recipient via the server mailbox as that device's personal cipher alphabet. This shuffled alphabet is saved to `known_ids.json` on the sender and `my_letters.json` on the recipient, so future sessions reuse the same key.
 
- `Cencrypt.cipher(message, alphabet)` — encrypts a plaintext string using the shuffled alphabet; returns the ciphertext and the key used for that message.
- `Cencrypt.decipher(ciphertext, alphabet)` — decrypts a message given the matching alphabet.
The combined message sent over the wire is `key + ciphertext` concatenated into a single string.
 
### Peer-to-Peer Messaging
 
Messaging is relayed through the Flask server's mailbox system rather than direct socket connections. Each device has a unique 9-digit numeric ID assigned at first boot.
 
**Sending** (`esp_network_server`):
1. If the target device ID is new, prompts the user (via voice recording) to name the contact, generates a shuffled cipher alphabet, and delivers it to the recipient via `POST /send-msg`.
2. Saves the shuffled alphabet to `known_ids.json` keyed by the target's device ID.
3. Encrypts the outbound message using the stored alphabet for that contact.
4. Posts the encrypted message to `POST /send-msg` with the destination device ID.
5. Saves the exchange (plaintext + ciphertext + timestamp + contact) to `history.json`.
**Receiving** (`esp_network_client`):
1. On entering receive mode (idle timeout), polls `GET /updates?Request=check_mail&dev_id=<id>` for new messages.
2. If no alphabet is stored in `my_letters.json`, retrieves and saves the one delivered by the sender.
3. Deciphers incoming messages using the stored alphabet, plays a notification chime, and displays the message on screen.
### Group Chat
 
The group chat feature routes through the Flask server:
 
1. The user sets a username on first use (recorded by voice, stored in `gc_username` for the session).
2. Messages are posted via `POST /gc` with the username, device ID, and message as parameters.
3. The server encrypts incoming messages with a single server-side shuffled alphabet (`ALPH`) and appends them to `messg_hist`.
4. Devices retrieve the server alphabet via `GET /updates?Request=serv_letters` and message history via `GET /updates?Request=prov_hist`, then decrypt locally with `Cencrypt.decipher`.
5. The web interface at `/gc` (served by `web_msg.html`) polls `GET /messages` and renders the encrypted message log in a browser — messages appear encrypted to anyone intercepting the HTTP traffic.
### Speech-to-Text
 
Audio is captured at 8 kHz mono using the ADC on pin 17. While the record button is held, 16-bit PCM samples are collected in memory. On release, a WAV file is written to flash (`recording.wav`) and uploaded via `POST /stt` to the Flask server, along with the device's ID.
 
The server processes the audio with **Vosk** (offline STT, no cloud dependency) using `vosk-model-small-en-us-0.15`. The transcribed text is returned as JSON and displayed on screen for confirmation before use. A simple filler-word filter (`processing()`) strips common hesitation words (`"uh"`, `"um"`, `"hmm"`, etc.) from the result.
 
---
 
## Server Setup
 
### Requirements
 
```bash
pip install flask vosk Cencrypt
```
 
Download the Vosk model and place it at `models/vosk-model-small-en-us-0.15/`:
```
https://alphacephei.com/vosk/models
```
 
You will also need [ngrok](https://ngrok.com/) installed and authenticated on the Raspberry Pi.
 
### Running
 
In one terminal, start the Flask server:
 
```bash
python server.py
```
 
In a separate terminal, start the ngrok tunnel:
 
```bash
ngrok http --url=blog-skipping-send.ngrok-free.dev 5000
```
 
The server listens on `0.0.0.0:5000` and is exposed publicly via the ngrok tunnel. Update the tunnel URL in `main.py` and `server.py` if your ngrok domain changes (search for `ngrok-free.dev`).
 
### Endpoints
 
| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/stt` | Accepts a WAV file + device ID, returns `{"text": "..."}` |
| `GET` | `/messages` | Returns full encrypted message history as JSON |
| `GET/POST` | `/gc` | Post a group chat message or view the web UI |
| `GET` | `/updates` | Returns server alphabet, message history, or mailbox for a device ID |
| `GET/POST` | `/getID` | Registers a new device ID; returns `"Clear"` if available or a new unique ID |
| `GET/POST` | `/send-msg` | Deposits a message into a device's mailbox by destination ID |
 
---
 
## Device Setup
 
1. Flash MicroPython to the ESP32.
2. Upload `main.py`, `Cencrypt.py`, and `ssd1680.py` to the device filesystem. `Cencrypt.py` can be downloaded from [PyPI](https://pypi.org/project/Cencrypt/) or installed via `mip` on the device.
3. Update the ngrok tunnel URL in `main.py` if your domain changes (search for `ngrok-free.dev`).
4. Power on — the device displays "HANDCRYPTION", plays the startup chime, and registers its device ID with the server on first boot.
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
| *(Idle timeout)* | `5` | Enter receive mode |
 
**Button reference:**
 
| Button | Role |
|--------|------|
| Record (hold) | Capture audio |
| Send | Open send-message flow |
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
| `device_ID.json` | This device's unique 9-digit ID, registered with the server on first boot |
| `known_ids.json` | `{ "device_id": [shuffled alphabet array], ... }` |
| `contacts.json` | `{ "Name": "device_id", ... }` |
| `history.json` | Array of sent message records (plaintext + ciphertext + timestamp + contact) |
| `my_letters.json` | Cipher alphabet received from sender (used in receive mode) |
| `recording.wav` | Temporary audio file, overwritten on each recording |
 
The **Settings → Reset** option wipes `contacts.json`, `history.json`, and `known_ids.json` back to empty — forcing a full re-handshake and new cipher key exchange on the next connection.
 
---
