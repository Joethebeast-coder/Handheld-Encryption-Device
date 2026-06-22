# Handcryption

A hardware-based encrypted peer-to-peer messaging device built on MicroPython (ESP32), with a companion Flask server for speech-to-text, message relay, and group chat support.

---

## Table of Contents

- [Overview](#overview)
- [Hardware](#hardware)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
  - [Wi-Fi Setup](#wi-fi-setup)
  - [Encryption (Cencrypt)](#encryption-cencrypt)
  - [Voice Message Encryption (RSA)](#voice-message-encryption-rsa)
  - [Peer-to-Peer Messaging](#peer-to-peer-messaging)
  - [Group Chat](#group-chat)
  - [Speech-to-Text](#speech-to-text)
- [Server Setup](#server-setup)
- [Device Setup](#device-setup)
- [UI & Navigation](#ui--navigation)
- [File Storage](#file-storage)
- [Credits](#credits)

---

## Overview

### [Video Overview (Pre-funding)](https://www.youtube.com/watch?v=kqKA_LZ2jB4)
Handcryption is a hardware-based encrypted peer-to-peer messaging device built around physical ESP32 devices and a Flask server hosted on a Raspberry Pi 4, exposed publicly via an ngrok tunnel. Messages can be sent as voice-transcribed text or as fully encrypted voice clips, transcribed/processed using a local Vosk speech-to-text model on the companion server, encrypted using a custom substitution cipher (text) or RSA-protected XOR cipher (voice), and relayed through the server's mailbox system. The device uses an e-ink display and physical buttons for all interaction — no smartphone or touchscreen required.

Each device is assigned a unique numeric ID on first boot, which is used to route messages and identify contacts. A secondary group chat feature allows multiple devices to post to a shared encrypted channel viewable in a basic web interface.

---

## Hardware

| Component | Purpose |
|-----------|---------|
| Adafruit ESP32-S2 Feather (MicroPython) | Main controller |
| SSD1680 e-ink display (250×128) | UI output via SPI |
| MAX17048 fuel gauge (I2C) | Battery percentage reading |
| DAC output (Pin 17) | Audio feedback chimes and voice message playback |
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
| 17 | Microphone (ADC) / Speaker (DAC) |
| 4/3 | I2C SCL/SDA (MAX17048) |
| 36/35/37 | SPI SCK/MOSI/MISO (e-ink) |
| 12/6/13/9 | E-ink DC/Busy/CS/Reset |

###

<img width="1169" height="827" alt="image" src="https://github.com/user-attachments/assets/9e2d81ae-9f03-4d98-8e92-48a024ba4375" />

---

## Project Structure

```
handcryption/
├── main.py              # ESP32 MicroPython firmware (device code)
├── server.py            # Flask server (STT + relay + group chat backend)
├── Cencrypt.py          # Custom substitution cipher (cipher/decipher)
├── ssd1680.py           # E-ink display driver
├── fonts.py             # Font data required by the e-ink display driver
├── models/
│   └── vosk-model-small-en-us-0.15/   # Vosk offline STT model
├── templates/
│   └── web_msg.html     # Group chat web interface
├── wifi.json            # Known Wi-Fi networks (auto-created)
├── known_ids.json       # Per-device-ID shuffled alphabet store (auto-created)
├── contacts.json        # Contact name → device ID map (auto-created)
├── history.json         # Outbound message log (auto-created)
├── my_letters.json      # Client-side cipher alphabet (auto-created)
├── gc_username.json     # Group chat username (auto-created)
├── priv_keys.json       # RSA key material for voice message encryption (auto-created)
└── device_ID.json       # This device's unique ID (auto-created on first boot)
```

---

## How It Works

### Wi-Fi Setup

On first boot (or if no known network is reachable), the device prompts the user to record a Wi-Fi name and password by voice. Since voice-to-text transcription of network credentials is error-prone, the device provides a character-by-character editor:

- **Up** — capitalize the current letter
- **Down** — lowercase the current letter
- **Select** — move to the next letter
- **Send** — toggle the current word between digit and word form (e.g., "five" ↔ "5"), useful for fixing numbers misheard as words

Once confirmed, the SSID/password pair is appended to a list in `wifi.json`. On every subsequent boot, the device tries each known network in order; if none connect within the timeout, it prompts for a new network and adds it to the list.

### Encryption (Cencrypt)

Handcryption uses [Cencrypt](https://pypi.org/project/Cencrypt/), a custom substitution cipher library available on PyPI, for text messages. The full printable character set (letters, digits, punctuation, space) is stored in `LETTERS`. When two devices connect for the first time, the sending device shuffles a copy of `LETTERS` and sends it to the recipient via the server mailbox as that device's personal cipher alphabet. This shuffled alphabet is saved to `known_ids.json` on the sender and `my_letters.json` on the recipient, so future sessions reuse the same key.

- `Cencrypt.cipher(message, alphabet)` — encrypts a plaintext string using the shuffled alphabet; returns the ciphertext and the key used for that message.
- `Cencrypt.decipher(ciphertext, alphabet)` — decrypts a message given the matching alphabet.

The combined message sent over the wire is `key + ciphertext` concatenated into a single string.

### Voice Message Encryption (RSA)

Voice messages use a separate encryption scheme since the substitution cipher only operates on text. Each device generates a 2048-bit RSA keypair on first boot (the server generates the large primes, since this is too slow on the microcontroller itself) and publishes its public key to the server.

To send a voice message:
1. A random 32-byte XOR key is generated locally.
2. The recorded PCM audio is XOR-encrypted with that key.
3. The XOR key itself is encrypted using the recipient's RSA public key (fetched from the server via `get_cont_pub_key`).
4. The encrypted key and encrypted audio are concatenated, base64-encoded, and sent through the mailbox with `"type": "audio"`.

On receipt, the recipient decrypts the XOR key using its own RSA private key, then XOR-decrypts the audio and plays it back through the DAC.

### Peer-to-Peer Messaging

Messaging is relayed through the Flask server's mailbox system rather than direct socket connections. Each device has a unique 9-digit numeric ID assigned at first boot.

**Sending** (`esp_network_server`):
1. If the target device ID is new, prompts the user (via voice recording) to name the contact, generates a shuffled cipher alphabet, and delivers it to the recipient via `POST /send-msg` with `"type": "key_exchange"`.
2. Saves the shuffled alphabet to `known_ids.json` keyed by the target's device ID.
3. For text messages: encrypts the outbound message using the stored alphabet for that contact and posts it with `"type": "txt"`.
4. For voice messages: encrypts the recorded audio using RSA as described above and posts it with `"type": "audio"`.
5. Saves text exchanges (plaintext + ciphertext + timestamp + contact) to `history.json`.

**Receiving** (`esp_network_client`):
1. On entering receive mode (idle timeout), polls `GET /updates?Request=check_mail&dev_id=<id>` for new messages.
2. Messages are dispatched by type:
   - `"key_exchange"` — saves the received alphabet to `my_letters.json`.
   - `"txt"` — deciphers using the stored alphabet, plays a notification chime, and displays the message.
   - `"audio"` — decrypts the RSA-protected audio and plays it back through the DAC.

### Group Chat

The group chat feature routes through the Flask server:

1. The user sets a username on first use (recorded by voice, persisted to `gc_username.json` so it only needs to be set once).
2. Messages are posted via `POST /gc` with the username, device ID, and message as parameters.
3. The server encrypts incoming messages with a single server-side shuffled alphabet (`ALPH`) and appends them to `messg_hist`.
4. Devices retrieve the server alphabet via `GET /updates?Request=serv_letters` and message history via `GET /updates?Request=prov_hist`, then decrypt locally with `Cencrypt.decipher`.
5. The web interface at `/gc` (served by `web_msg.html`) polls `GET /messages` every 2 seconds and renders the encrypted message log in a browser — messages appear encrypted to anyone intercepting the HTTP traffic.

### Speech-to-Text

Audio is captured at 8 kHz mono using the ADC on pin 17. While the record button is held, 16-bit PCM samples are collected in memory. On release, a WAV file is written to flash (`recording.wav`) and uploaded via `POST /stt` to the Flask server, along with the device's ID.

The server processes the audio with **Vosk** (offline STT, no cloud dependency) using `vosk-model-small-en-us-0.15`. The transcribed text is returned as JSON and displayed on screen for confirmation before use. A simple filler-word filter (`processing()`) strips common hesitation words (`"uh"`, `"um"`, `"hmm"`, etc.) from the result.

---

## Server Setup

### Requirements

```bash
pip install flask vosk Cencrypt pycryptodome
```

Download the Vosk model and place it at `models/vosk-model-small-en-us-0.15/`:
```
https://alphacephei.com/vosk/models
```

You will also need [ngrok](https://ngrok.com/) installed and authenticated on the Raspberry Pi.

> **Note:** This example uses a personal ngrok domain (`blog-skipping-send.ngrok-free.dev`). For your own set of devices, create your own domain and update the hardcoded URLs in both `main.py` and `server.py`.

### Running

In one terminal, start the Flask server:

```bash
python server.py
```

In a separate terminal, start the ngrok tunnel:

```bash
ngrok http --url=your-url.dev 5000
```

The server listens on `0.0.0.0:5000` and is exposed publicly via the ngrok tunnel.

### Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/stt` | Accepts a WAV file + device ID, returns `{"text": "..."}` |
| `GET` | `/messages` | Returns full encrypted group chat message history as JSON (polled by the web UI) |
| `GET/POST` | `/gc` | Post a group chat message or view the web UI |
| `GET/POST` | `/updates` | Returns server alphabet, group chat history, mailbox contents, RSA public keys, or stores a public key, depending on `Request` |
| `GET/POST` | `/getID` | Registers a new device ID; returns `"Clear"` if available or a new unique ID |
| `GET/POST` | `/send-msg` | Deposits a message (text, audio, or key exchange) into a device's mailbox by destination ID |
| `GET/POST` | `/get_prime` | Generates a 2048-bit RSA keypair's components for a requesting device |

---

## Device Setup

1. Flash MicroPython to the ESP32.
2. Upload `main.py`, `Cencrypt.py`, `ssd1680.py`, and `fonts.py` to the device filesystem. `Cencrypt.py` can be downloaded from [PyPI](https://pypi.org/project/Cencrypt/) or installed via `mip` on the device. `fonts.py` is required by the `ssd1680.py` driver — see [Credits](#credits).
3. Update the ngrok tunnel URL throughout `main.py` if your domain changes (search for `ngrok-free.dev`).
4. Power on — on first boot, the device will prompt you to record a Wi-Fi network name and password (see [Wi-Fi Setup](#wi-fi-setup)).
5. After connecting, the device displays "HANDCRYPTION", plays the startup chime, registers its device ID with the server, and generates its RSA keypair for voice messages.

---

## UI & Navigation

The main menu has four options navigated with **Up/Down** and confirmed with **Select**:

| Icon | Option | Action |
|------|--------|--------|
| History (left) | `0` | Browse past sent messages |
| Contacts (center) | `1` | View or add contacts |
| Settings (right) | `2` | Reset data or adjust volume |
| Message bubble (top) | `3` | Access group chat |
| *(Send button)* | `4` | Send a direct message — choose text or voice |
| *(Idle timeout)* | `5` | Enter receive mode |

When sending a direct message (`4`), the device asks whether to send as **text** (Up) or **voice** (Down). Text messages go through the usual record → transcribe → confirm flow. Voice messages are recorded, encrypted with the recipient's RSA public key, and sent as raw encrypted audio without transcription.

**Button reference:**

| Button | Role |
|--------|------|
| Record (hold) | Capture audio, or go back in some cases |
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
| `wifi.json` | Array of known Wi-Fi networks as `[ssid, password]` pairs, tried in order on boot |
| `device_ID.json` | This device's unique 9-digit ID, registered with the server on first boot |
| `gc_username.json` | The username used for group chat, set on first use of that feature |
| `priv_keys.json` | RSA key material (`phi/d/n/key1/key2`) used for encrypting/decrypting voice messages |
| `known_ids.json` | `{ "device_id": [shuffled alphabet array], ... }` |
| `contacts.json` | `{ "Name": "device_id", ... }` |
| `history.json` | Array of sent message records (plaintext + ciphertext + timestamp + contact) |
| `my_letters.json` | Cipher alphabet received from sender (used in receive mode) |
| `recording.wav` | Temporary audio file, overwritten on each recording |

The **Settings → Reset** option wipes `contacts.json`, `history.json`, and `known_ids.json` back to empty — forcing a full re-handshake and new cipher key exchange on the next connection.

---

## Credits

The SSD1680 e-ink display driver (`ssd1680.py`) and its accompanying `fonts.py` used in this project are based on work by [hfwang132](https://github.com/hfwang132), available at [hfwang132/ssd1680-micropython-drivers](https://github.com/hfwang132/ssd1680-micropython-drivers/tree/main). Many thanks for the MicroPython driver that made the display portion of this project possible. 

## AI Usage

AI was used to help find bugs in my code.

---
