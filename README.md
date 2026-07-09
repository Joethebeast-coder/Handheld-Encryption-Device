# Handcryption

A hardware-based encrypted peer-to-peer messaging device built on **CircuitPython** (ESP32-S2), with a companion Flask server for speech-to-text, message relay, and group chat support.

---
## Pre-funding Images
___
### Shell Top
<img width="900" height="1193" alt="IMG_E3014" src="https://github.com/user-attachments/assets/7ab689f4-8a87-4041-b5ef-dbc83837650f" />

### Shell Bottom
<img width="900" height="1193" alt="IMG_E3015" src="https://github.com/user-attachments/assets/0e711094-95b3-4a51-96f7-fceeb1a945d7" />

---
## Final Images
___
### Shell Top
<img width="3021" height="3570" alt="IMG_E3039" src="https://github.com/user-attachments/assets/530c84e8-49d5-4011-9c68-c96f48a9b8c7" />

### Shell Bottom
<img width="3024" height="4032" alt="IMG_3040" src="https://github.com/user-attachments/assets/e3bbb86f-cf84-4080-9c5f-0e0e1cc2e643" />

___
## Table of Contents

- [Overview](#overview)
- [Hardware](#hardware)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
  - [Wi-Fi Setup](#wi-fi-setup)
  - [Server Connection & Authentication](#server-connection--authentication)
  - [Encryption (Cencrypt)](#encryption-cencrypt)
  - [Voice Message Encryption (RSA)](#voice-message-encryption-rsa)
  - [Peer-to-Peer Messaging](#peer-to-peer-messaging)
  - [Group Chat](#group-chat)
  - [Speech-to-Text](#speech-to-text)
  - [Text & Voice Input](#text--voice-input)
- [Server Setup](#server-setup)
- [Device Setup](#device-setup)
- [UI & Navigation](#ui--navigation)
- [File Storage](#file-storage)
- [Credits](#credits)

---

## Overview

### [Video Overview (Pre-funding)](https://www.youtube.com/watch?v=kqKA_LZ2jB4)
### [Full Build Test](https://youtu.be/IIfR6bDeaTY)

Handcryption is a hardware-based encrypted peer-to-peer messaging device built around physical ESP32-S2 devices and a Flask server hosted on a Raspberry Pi 4, exposed publicly via a **Cloudflare tunnel**. Messages can be sent as transcribed text or as fully encrypted voice clips. Text is transcribed by a local Vosk speech-to-text model on the companion server (or typed directly on the device), encrypted using a custom substitution cipher (text) or an RSA-protected XOR cipher (voice), and relayed through the server's mailbox system. The device uses an e-ink display and physical buttons for all interaction — no smartphone or touchscreen required.

Each device is assigned a unique numeric ID on first boot, which is used to route messages and identify contacts. A secondary group chat feature allows multiple devices to post to a shared encrypted channel viewable in a basic web interface.

> **Note on the platform:** This project originally targeted MicroPython. It now runs on **CircuitPython** (tested on CircuitPython 10.x for the Feather ESP32-S2). Display output uses Adafruit's `adafruit_epd` library rather than a standalone MicroPython driver, and several standard-library gaps in CircuitPython (e.g. `random.shuffle`, `os.path`) are worked around in the device code.

---

## Hardware

| Component | Purpose |
|-----------|---------|
| Adafruit ESP32-S2 Feather (CircuitPython) | Main controller |
| Adafruit 2.13" SSD1680 monochrome e-ink display (250×122) | UI output via SPI |
| MAX17048 fuel gauge (I2C) | Battery percentage reading |
| DAC output | Audio feedback chimes and voice message playback (via amplifier) |
| Analog microphone (ADC) | Voice recording at 16 kHz |
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
| A0 | Speaker (PWM, via amplifier) |
| A1 | Microphone (ADC) |
| 4/3 | I2C SCL/SDA (MAX17048) |
| 36/35/37 | SPI SCK/MOSI/MISO (e-ink) |
| 12/6/13/9 | E-ink DC/Busy/CS/Reset |

###

<img width="1169" height="827" alt="image" src="https://github.com/user-attachments/assets/9e2d81ae-9f03-4d98-8e92-48a024ba4375" />

---

## Project Structure

```
handcryption/
├── code.py              # ESP32-S2 CircuitPython firmware (device code)
├── settings.toml        # Server URL + auth token (see Device Setup)
├── server.py            # Flask server (STT + relay + group chat backend)
├── Cencrypt.py          # Custom substitution cipher (cipher/decipher)
├── font5x8.bin          # Bitmap font used by adafruit_epd text rendering
├── lib/
│   ├── adafruit_epd/    # E-ink display library
│   ├── adafruit_requests/
│   ├── adafruit_connection_manager/
│   └── adafruit_framebuf/
├── models/
│   └── vosk-model-small-en-us-0.15/   # Vosk offline STT model (server-side)
├── templates/
│   └── web_msg.html     # Group chat web interface (server-side)
├── wifi.json            # Known Wi-Fi networks (auto-created)
├── known_ids.json       # Per-device-ID shuffled alphabet store (auto-created)
├── contacts.json        # Contact name → device ID map (auto-created)
├── history.json         # Message log, sent and received (auto-created)
├── my_letters.json      # Client-side cipher alphabet (auto-created)
├── gc_username.json     # Group chat username (auto-created)
├── priv_keys.json       # RSA key material for voice message encryption (auto-created)
└── device_ID.json       # This device's unique ID (auto-created on first boot)
```

> On CircuitPython, the main firmware file is named `code.py` on the device. The libraries under `lib/` come from the Adafruit CircuitPython library bundle.

---

## How It Works

### Wi-Fi Setup

On first boot (or if no known network is reachable), the device prompts the user to record a Wi-Fi name and password by voice. Since voice-to-text transcription of network credentials is error-prone, the device provides a character-by-character editor:

- **Up** — capitalize the current letter
- **Down** — lowercase the current letter
- **Select** — move to the next letter
- **Send** — toggle the current word between digit and word form (e.g., "five" ↔ "5"), useful for fixing numbers misheard as words

Once confirmed, the SSID/password pair is appended to a list in `wifi.json`. On every subsequent boot, the device tries each known network in order; if none connect within the timeout, it prompts for a new network and adds it to the list.

### Server Connection & Authentication

The device does not hardcode a server address. Instead, the server URL and a shared authentication token are read from `settings.toml`:

```
SERVER_URL = "https://your-endpoint.example.com"
DEVICE_TOKEN = "your-long-random-shared-secret"
```

All requests to the server include an `X-Auth` header carrying the token, and the Flask server rejects any request without the matching token (HTTP 401). This keeps the publicly reachable endpoint from being driven by anyone who discovers the URL.

Because the server is reached over an outbound tunnel, the device works from any network with internet access — the Raspberry Pi does not need port forwarding or a static public IP.

### Encryption (Cencrypt)

Handcryption uses [Cencrypt](https://pypi.org/project/Cencrypt/), a custom substitution cipher library available on PyPI, for text messages. The full printable character set (letters, digits, punctuation, space) is stored in `LETTERS`. When two devices connect for the first time, the sending device shuffles a copy of `LETTERS` and sends it to the recipient via the server mailbox as that device's personal cipher alphabet. This shuffled alphabet is saved to `known_ids.json` on the sender and `my_letters.json` on the recipient, so future sessions reuse the same key.

- `Cencrypt.cipher(message, alphabet)` — encrypts a plaintext string using the shuffled alphabet; returns the ciphertext and the key used for that message.
- `Cencrypt.decipher(ciphertext, alphabet)` — decrypts a message given the matching alphabet.

The combined message sent over the wire is `key + ciphertext` concatenated into a single string.

> **Note:** CircuitPython's `random` module has no `shuffle()`, so the device implements a Fisher–Yates shuffle internally to build cipher alphabets.

### Voice Message Encryption (RSA)

Voice messages use a separate encryption scheme since the substitution cipher only operates on text. Each device generates a 2048-bit RSA keypair on first boot (the server generates the large primes, since this is too slow on the microcontroller itself) and publishes its public key to the server. The public key is re-published on every boot, so a failed first-boot upload self-heals on the next start.

To send a voice message:
1. A random XOR key is generated locally.
2. The recorded PCM audio is XOR-encrypted with that key.
3. The XOR key itself is encrypted using the recipient's RSA public key (fetched from the server via `get_cont_pub_key`).
4. The encrypted key and encrypted audio are concatenated, base64-encoded, and sent through the mailbox with `"type": "audio"`.

On receipt, the recipient decrypts the XOR key using its own RSA private key, then XOR-decrypts the audio and plays it back through the speaker. If no public key is on file for the target contact, the device reports this instead of failing.

> **Note:** Audio messaging is the most fragile feature of the device. Because capture relies on a simple analog microphone (sampled directly through the ADC, with no dedicated audio codec or noise handling), recordings are prone to noise, clipping, and inconsistent levels. This affects both voice messages and speech-to-text accuracy. Text input (typed or transcribed) is the more reliable path; treat voice messages as best-effort.

### Peer-to-Peer Messaging

Messaging is relayed through the Flask server's mailbox system rather than direct socket connections. Each device has a unique 9-digit numeric ID assigned at first boot.

**Sending** (`esp_network_server`):
1. If the target device ID is new, prompts the user to name the contact (by voice or by typing), generates a shuffled cipher alphabet, and delivers it to the recipient via `POST /send-msg` with `"type": "key_exchange"`.
2. Saves the shuffled alphabet to `known_ids.json` keyed by the target's device ID. (Because JSON object keys are strings, device IDs are handled as strings for these lookups.)
3. For text messages: encrypts the outbound message using the stored alphabet for that contact and posts it with `"type": "txt"`.
4. For voice messages: encrypts the recorded audio using RSA as described above and posts it with `"type": "audio"`.
5. Saves the exchange to `history.json`.

**Receiving** (`esp_network_client`):
1. On entering receive mode, polls `GET /updates?Request=check_mail&dev_id=<id>` for new messages. Press **Record** to leave receive mode and return to the menu.
2. Messages are dispatched by type:
   - `"key_exchange"` — saves the received alphabet to `my_letters.json`.
   - `"txt"` — deciphers using the stored alphabet, plays a notification chime, displays the message, and logs it to `history.json`.
   - `"audio"` — decrypts the RSA-protected audio and plays it back.

### Group Chat

The group chat feature routes through the Flask server:

1. The user sets a username on first use (by voice or typing, persisted to `gc_username.json` so it only needs to be set once).
2. Messages are posted via `POST /gc` with the username, device ID, and message as parameters.
3. The server encrypts incoming messages with a single server-side shuffled alphabet (`ALPH`) and appends them to `messg_hist`.
4. Devices retrieve the server alphabet via `GET /updates?Request=serv_letters` and message history via `GET /updates?Request=prov_hist`, then decrypt locally with `Cencrypt.decipher`.
5. The web interface at `/gc` (served by `web_msg.html`) polls `GET /messages` every 2 seconds and renders the encrypted message log in a browser — messages appear encrypted to anyone intercepting the HTTP traffic.

### Speech-to-Text

Audio is captured at **16 kHz** mono using the ADC. While the record button is held, 16-bit PCM samples are collected in memory. On release, a WAV file is written to flash (`recording.wav`) and uploaded via `POST /stt` to the Flask server, along with the device's ID.

The server processes the audio with **Vosk** (offline STT, no cloud dependency) using `vosk-model-small-en-us-0.15`. The transcribed text is returned as JSON and displayed on screen for confirmation before use. A simple filler-word filter (`processing()`) strips common hesitation words (`"uh"`, `"um"`, `"hmm"`, etc.) from the result.

> The recording sample rate (16 kHz) matches the rate the Vosk model expects. Recording at a mismatched rate (e.g. 8 kHz) causes the server to reject the audio.

### Text & Voice Input

Anywhere the device asks for input — contact names, contact IDs, message text, and group chat — you can either **record by voice** or **type on the device**:

- At a record prompt, press **Up** to switch to the on-screen text editor instead of recording.
- In the text editor: **Up/Down** scroll through characters, **Select** commits the current character, **Record** (tap) is backspace, **Record** (hold ~1s) exits, and **Send** finishes.

This makes the device usable even when speech-to-text is unavailable or inaccurate.

---

## Server Setup

### Requirements

```bash
pip install flask waitress vosk Cencrypt pycryptodome
```

Download the Vosk model and place it at `models/vosk-model-small-en-us-0.15/`:
```
https://alphacephei.com/vosk/models
```

You will also need a way to expose the server publicly. This project uses a **Cloudflare tunnel** (`cloudflared`) running on the Raspberry Pi, which requires no port forwarding and works behind CGNAT.

### Authentication token

The server reads a shared secret from the `DEVICE_TOKEN` environment variable and rejects any request whose `X-Auth` header does not match. Set the same value here and in each device's `settings.toml`.

### Running

Run the Flask app under a production server (Waitress) so it survives long-running use:

```bash
DEVICE_TOKEN=your-long-random-shared-secret \
  waitress-serve --port=5000 server:app
```

In a separate terminal (or as a service), start the tunnel:

```bash
cloudflared tunnel --url http://localhost:5000
```

`cloudflared` prints a public HTTPS URL. Put that URL in each device's `settings.toml` as `SERVER_URL`. For a permanent address that survives restarts, use a **named** Cloudflare tunnel with your own domain instead of the quick-tunnel URL.

> For an always-on setup, run both the Flask server and `cloudflared` as `systemd` services so they restart on boot.

### Endpoints

All endpoints require the `X-Auth` header.

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

1. Flash **CircuitPython** to the ESP32-S2 Feather.
2. Copy the required libraries into `lib/` from the Adafruit CircuitPython library bundle: `adafruit_epd`, `adafruit_requests`, `adafruit_connection_manager`, and `adafruit_framebuf`. Also copy `font5x8.bin` to the drive root (used for text rendering).
3. Upload `code.py` (the device firmware), `Cencrypt.py`, and the `settings.toml` file to the device. `Cencrypt.py` can be downloaded from [PyPI](https://pypi.org/project/Cencrypt/).
4. Edit `settings.toml` with your server URL and token:
   ```
   SERVER_URL = "https://your-endpoint.example.com"
   DEVICE_TOKEN = "your-long-random-shared-secret"
   ```
5. Power on — on first boot, the device will prompt you to record or type a Wi-Fi network name and password (see [Wi-Fi Setup](#wi-fi-setup)).
6. After connecting, the device displays "HANDCRYPTION", plays the startup chime, registers its device ID with the server, generates its RSA keypair for voice messages, and publishes its public key.

---

## UI & Navigation

The main menu has four icon options navigated with **Up/Down** and confirmed with **Select**. The currently highlighted option is drawn with a border box.

| Icon | Option | Action |
|------|--------|--------|
| History | `0` | Browse past messages (sent and received) |
| Contacts | `1` | View or add contacts |
| Settings | `2` | Reset data or adjust volume |
| Message bubble | `3` | Access group chat |
| *(Send button)* | `4` | Send a direct message — choose text or voice |
| *(Idle timeout)* | `5` | Enter receive mode |

When sending a direct message (`4`), the device asks whether to send as **text** (Up) or **voice** (Down). Text messages go through the record-or-type → (transcribe) → confirm flow. Voice messages are recorded, encrypted with the recipient's RSA public key, and sent as raw encrypted audio without transcription.

**Button reference:**

| Button | Role |
|--------|------|
| Record | Capture audio (hold); in the text editor, tap = backspace, hold = exit; also "go back" in some screens |
| Send | Open send-message flow / confirm in text editor |
| Select | Confirm selection / commit character in text editor |
| Up / Down | Navigate menus and characters; Up also switches a record prompt to typing |
| Shut Off (hold 1s+) | Deep sleep (wakes on next power press) |

**Display note:** The e-ink panel performs full refreshes only. The UI is designed to refresh once per screen change rather than continuously, so navigation updates when a selection changes rather than animating.

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
| `settings.toml` | `SERVER_URL` and `DEVICE_TOKEN` (server address + auth secret) |
| `wifi.json` | Array of known Wi-Fi networks as `[ssid, password]` pairs, tried in order on boot |
| `device_ID.json` | This device's unique 9-digit ID, registered with the server on first boot |
| `gc_username.json` | The username used for group chat, set on first use of that feature |
| `priv_keys.json` | RSA key material (`phi/d/n/key1/key2`) used for encrypting/decrypting voice messages |
| `known_ids.json` | `{ "device_id": [shuffled alphabet array], ... }` (keys stored as strings) |
| `contacts.json` | `{ "Name": "device_id", ... }` |
| `history.json` | Array of message records; sent entries carry a `To` field, received entries carry a `From` field |
| `my_letters.json` | Cipher alphabet received from sender (used in receive mode) |
| `recording.wav` | Temporary audio file, overwritten on each recording |

The **Settings → Reset** option wipes `contacts.json`, `history.json`, and `known_ids.json` back to empty — forcing a full re-handshake and new cipher key exchange on the next connection.

---

## Credits

This project began as a MicroPython build and was ported to **CircuitPython**. The e-ink display now uses Adafruit's [`adafruit_epd`](https://github.com/adafruit/Adafruit_CircuitPython_EPD) library.

The original MicroPython SSD1680 display driver and font work that inspired the earlier version of this project were based on work by [hfwang132](https://github.com/hfwang132), available at [hfwang132/ssd1680-micropython-drivers](https://github.com/hfwang132/ssd1680-micropython-drivers/tree/main). Many thanks for the MicroPython driver that made the display portion of the original project possible.

## AI Usage

AI was used to help find and fix bugs in the code, mainly when I converted the project from MicroPython to CircuitPython.

---
