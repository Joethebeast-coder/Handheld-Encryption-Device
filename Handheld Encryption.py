import os
import time
import math
import random
import binascii

def shuffle_in_place(seq):
    # CircuitPython's random module has no shuffle(); implement Fisher-Yates.
    for i in range(len(seq) - 1, 0, -1):
        j = random.randint(0, i)
        seq[i], seq[j] = seq[j], seq[i]
    return seq

import json
import board
import digitalio
import busio
import analogio
import pwmio
import displayio
import wifi
import socketpool
import ssl
import adafruit_requests as requests
from fourwire import FourWire
from adafruit_display_text import label
import terminalio
import busio
import digitalio
from adafruit_epd.ssd1680 import Adafruit_SSD1680
from adafruit_epd.epd import Adafruit_EPD

BASE_URL = os.getenv("SERVER_URL")
DEVICE_TOKEN = os.getenv("DEVICE_TOKEN")

# Map MicroPython timing and json module names to their standard names
utime = time
ujson = json

def file_exists(filename):
    try:
        os.stat(filename)
        return True
    except OSError:
        return False
    
# Keep your custom encryption logic intact
import Cencrypt as ce

# Helper to automatically translate integer pin numbers to your board's pins
def get_board_pin(pin_num):
    pin_obj = getattr(board, f"D{pin_num}", None)
    if pin_obj is None:
        pin_obj = getattr(board, f"A{pin_num}", None)
    return pin_obj

# ____________________________ Pin & Button Compatibility Wrapper ____________________________
class PinWrapper:
    IN = "in"
    PULL_UP = "pull_up"
    OUT = "out"
    
    def __init__(self, pin_num, direction=None, pull=None):
        pin_obj = get_board_pin(pin_num)
        if pin_obj is None:
            raise ValueError(f"Pin {pin_num} could not be mapped to your board layout.")
            
        self._raw_pin = pin_obj      # kept for deep-sleep PinAlarm
        self._pull_up = (pull == PinWrapper.PULL_UP)
        self.pin = digitalio.DigitalInOut(pin_obj)
        if direction == PinWrapper.OUT:
            self.pin.direction = digitalio.Direction.OUTPUT
        else:
            self.pin.direction = digitalio.Direction.INPUT
            if pull == PinWrapper.PULL_UP:
                self.pin.pull = digitalio.Pull.UP

    def release(self):
        # Free the pin so alarm.pin.PinAlarm can use it for deep sleep.
        try:
            self.pin.deinit()
        except Exception:
            pass
                
    def value(self, val=None):
        if val is not None:
            self.pin.value = bool(val)
            return
        # Active-low buttons: pressed returns 0, unpressed returns 1 to match MicroPython
        return 0 if not self.pin.value else 1

# Overwrite the Pin call to use our compatibility wrapper
Pin = PinWrapper

# Instantiates buttons exactly as named in your original codebase
record_button = Pin(5, Pin.IN, Pin.PULL_UP) 
send_mes_button = Pin(15, Pin.IN, Pin.PULL_UP)
select_button = Pin(39, Pin.IN, Pin.PULL_UP)
up = Pin(8, Pin.IN, Pin.PULL_UP)
down = Pin(38, Pin.IN, Pin.PULL_UP)
shut_off = Pin(16, Pin.IN, Pin.PULL_UP)

# ____________________________________ Voltage Sensing ____________________________________
MAX17048_ADDR = 0x36
i2c_bus = busio.I2C(get_board_pin(4), get_board_pin(3))  

def read_register(reg):
    while not i2c_bus.try_lock():
        pass
    try:
        buffer = bytearray(2)
        i2c_bus.writeto_then_readfrom(MAX17048_ADDR, bytes([reg]), buffer)
        return (buffer[0] << 8) | buffer[1]
    finally:
        i2c_bus.unlock()

def get_percent():
    raw = read_register(0x04)
    return raw / 256

def draw_battery(epd_obj, percent, x, y): 
    percent = max(0, min(100, percent))
    width = 30
    height = 12
    nub_width = 3

    epd_obj.draw_rectangle(x, y, x + width, y + height)
    epd_obj.draw_rectangle(x + width, y + 3, x + width + nub_width, y + height - 3)

    fill_width = int((width - 4) * (percent / 100))
    for fy in range(y + 2, y + height - 1):
        epd_obj.draw_line(x + 2, fy, x + 2 + fill_width, fy)

# ______________________________________ Piezo Setup ______________________________________
# Hardware PWM removes heavy CPU math and microsecond-loop lagging
pwm_speaker = pwmio.PWMOut(board.A0, frequency=30000, duty_cycle=0, variable_frequency=True)

def play_tone(frequency, percent_vol=1, duration=0.3, sample_rate=8000): 
    pwm_speaker.frequency = int(frequency)
    # A 50% duty cycle (32768) represents maximum square wave volume
    pwm_speaker.duty_cycle = int(32768 * max(0, min(1, percent_vol)))
    time.sleep(duration)
    pwm_speaker.duty_cycle = 0

def notif_chime(percent_vol=1):
    play_tone(3000, percent_vol, 0.3)
    play_tone(2000, percent_vol, 0.3)
    play_tone(1000, percent_vol, 0.3)
    play_tone(3000, percent_vol, 0.3)

def handcryption_chime(percent_vol=1):
    tones = [(1800, 0.18), (1400, 0.15), (900, 0.12), (1600, 0.15), (2200, 0.20), (2600, 0.10)]
    for freq, duration in tones:
        play_tone(freq, percent_vol, duration)

def wake_chime(percent_vol=1):
    play_tone(1500, percent_vol, 0.15)
    play_tone(3000, percent_vol, 0.3)

def shut_off_chime(percent_vol=1):
    play_tone(3000, percent_vol, 0.15)
    play_tone(2000, percent_vol, 0.15)
    play_tone(1000, percent_vol, 0.15)

# ______________________________________ E-ink Setup ______________________________________
displayio.release_displays()

class Color:
    WHITE = 1
    BLACK = 0

_spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
_ecs  = digitalio.DigitalInOut(get_board_pin(13))
_dc   = digitalio.DigitalInOut(get_board_pin(12))
_rst  = digitalio.DigitalInOut(get_board_pin(9))
_busy = digitalio.DigitalInOut(get_board_pin(6))

# native panel dims are (122, 250); rotation=1 gives landscape 250x122
_display = Adafruit_SSD1680(122, 250, _spi,
    cs_pin=_ecs, dc_pin=_dc, sramcs_pin=None, rst_pin=_rst, busy_pin=_busy)

_display.rotation = 3

class EPDCompatibilityWrapper:
    def __init__(self, display_obj):
        self.display = display_obj
        self.width = display_obj.width
        self.height = display_obj.height
        self.y_off = 10      # set to 8 or -8 if the image is shifted vertically
        self.x_off = 0      # set to 8 or -8 if shifted horizontally

    def init(self):
        pass

    def clear(self, color=None):
        self.display.fill(Adafruit_EPD.WHITE)

    def show_string(self, text, x, y):
        self.display.text(text, x + self.x_off, y + self.y_off, Adafruit_EPD.BLACK)

    def draw_rectangle(self, x1, y1, x2, y2):
        x, y = min(x1, x2) + self.x_off, min(y1, y2) + self.y_off
        w, h = max(1, abs(x2 - x1)), max(1, abs(y2 - y1))
        self.display.rect(x, y, w, h, Adafruit_EPD.BLACK)

    def draw_line(self, x1, y1, x2, y2):
        self.display.line(x1 + self.x_off, y1 + self.y_off,
                          x2 + self.x_off, y2 + self.y_off, Adafruit_EPD.BLACK)

    def show_bitmap(self, bitmap, x, y):
        if not bitmap or not bitmap[0]:
            return
        for row_i, row in enumerate(bitmap):
            for col_i, pixel in enumerate(row):
                if pixel:
                    self.display.pixel(x + col_i + self.x_off,
                                       y + row_i + self.y_off, Adafruit_EPD.BLACK)

    def update(self):
        self.display.display()

epd = EPDCompatibilityWrapper(_display)
epd.clear(Color.WHITE)

# _____________________________________ Voice to Text _____________________________________
mic_adc = analogio.AnalogIn(board.A1)
SAMPLE_RATE = 16000 
FILENAME = "recording.wav" 

def write_wav_header(file, num_samples):
    file.write(b"RIFF")
    file.write((36 + num_samples).to_bytes(4, "little"))
    file.write(b"WAVEfmt ")
    file.write((16).to_bytes(4, "little"))
    file.write((1).to_bytes(2, "little"))      
    file.write((1).to_bytes(2, "little"))      
    file.write(SAMPLE_RATE.to_bytes(4, "little"))
    file.write((SAMPLE_RATE * 2).to_bytes(4, "little"))
    file.write((2).to_bytes(2, "little"))      
    file.write((16).to_bytes(2, "little"))     
    file.write(b"data")
    file.write(num_samples.to_bytes(4, "little"))

def collect_audio(samples):
    raw = mic_adc.value >> 4          
    samples.append(raw.to_bytes(2, "little"))
    time.sleep(0.000125)   
    return samples

#_________________________________Entering Text__________________________________________
def text_entry(prompt="Enter text:"):
    """
    Manual text entry using buttons (fallback for voice).
      up / down  = scroll through characters
      select     = commit the current character
      record     = tap: backspace (delete last committed char)
                   hold ~1s: exit typing, returns what's typed so far
      send_mes   = done, returns the string
    Only refreshes the e-ink when something actually changes.
    """
    charset = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ")  # space at end
    idx = 0
    text = ""
    dirty = True   # redraw needed

    while True:
        if dirty:
            epd.clear(Color.WHITE)
            wrap_text(epd, prompt, 6, 4)
            # show the string being built
            shown = text if text else "_"
            wrap_text(epd, shown, 6, 30)
            # show the current character choice, marked
            cur = charset[idx]
            label_cur = "[space]" if cur == " " else cur
            epd.show_string("Char: " + label_cur, 6, 60)
            epd.show_string("sel=add rec=del send=done", 6, 90)
            epd.show_string("hold rec=exit", 6, 104)
            epd.update()
            dirty = False

        if up.value() == 0:
            idx = (idx + 1) % len(charset)
            dirty = True
            time.sleep(0.2)
        elif down.value() == 0:
            idx = (idx - 1) % len(charset)
            dirty = True
            time.sleep(0.2)
        elif select_button.value() == 0:
            text += charset[idx]
            dirty = True
            time.sleep(0.25)
        elif record_button.value() == 0:
            # Tap = backspace. Hold ~1s = exit typing and return what's typed.
            press_start = time.time()
            held_long = False
            while record_button.value() == 0:
                if time.time() - press_start >= 1.0:
                    held_long = True
                    break
                time.sleep(0.02)
            if held_long:
                # wait for release so the hold isn't re-read by the caller
                while record_button.value() == 0:
                    time.sleep(0.02)
                time.sleep(0.2)
                return text
            text = text[:-1]      # short tap = backspace
            dirty = True
            time.sleep(0.15)
        elif send_mes_button.value() == 0:
            time.sleep(0.25)
            return text
        else:
            machine.idle()

def record_or_type(dev_id=None, type_prompt="Type your response:", timeout=60):
    """
    Waits at a record/type prompt. If the user presses 'record', it records
    audio and returns the transcribed text (same behaviour as before). If the
    user presses 'up', it opens text_entry() and returns the typed string.
    Returns "" if nothing was entered within the timeout.
    """
    now_time = time.time()
    while time.time() - now_time < timeout:
        if record_button.value() == 0:
            samples = []
            while record_button.value() == 0:
                samples = collect_audio(samples)
            with open(FILENAME, "wb") as f:
                write_wav_header(f, len(samples) * 2)
                for s in samples:
                    f.write(s)
            return request_n_parse_translation(dev_id)
        elif up.value() == 0:
            time.sleep(0.2)
            return text_entry(type_prompt)
        machine.idle()
    return ""

# ____________________________Network & Request Compatibility ___________________________
class WLANCompatibility:
    class WLAN:
        IF_STA = 1  # Standard MicroPython constant
        
        def __init__(self, interface_id):
            pass
            
        def isconnected(self):
            # Explicitly import wifi to ensure we hit the global CircuitPython module
            import wifi
            return wifi.radio.connected
            
        def active(self, state):
            pass
            
        def connect(self, ssid, password):
            import wifi
            wifi.radio.connect(ssid, password)

pool = socketpool.SocketPool(wifi.radio)
ssl_context = ssl.create_default_context()

ssl_context.check_hostname = False

_requests_session = requests.Session(pool, ssl_context)
network = WLANCompatibility()

class UrequestsWrapper:
    def _with_retry(self, fn, retries=4, backoff=1.5):
        last = None
        for attempt in range(retries):
            try:
                return fn()
            except (OSError, RuntimeError) as e:
                last = e
                print(f"HTTP attempt {attempt + 1}/{retries} failed: {e}")
                # Free any half-open/stuck sockets before trying again
                try:
                    adafruit_connection_manager.connection_manager_close_all(pool)
                except Exception:
                    pass
                time.sleep(backoff * (attempt + 1))
        raise last

    def post(self, url, data=None, json=None, files=None, headers=None, **kwargs):
        if headers is None:
            headers = {}
        headers["X-Auth"] = DEVICE_TOKEN

        if files:
            boundary = f"----CPBoundary{random.randint(100000, 999999)}"
            body = bytearray()
            if isinstance(data, dict):
                for k, v in data.items():
                    body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
            for field, file_obj in files.items():
                body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"recording.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode())
                body.extend(file_obj.read())
                body.extend(b"\r\n")
            body.extend(f"--{boundary}--\r\n".encode())
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            frozen = bytes(body)
            return self._with_retry(lambda: _requests_session.post(url, data=frozen, headers=headers, **kwargs))
        return self._with_retry(lambda: _requests_session.post(url, data=data, json=json, headers=headers, **kwargs))

    def get(self, url, **kwargs):
        headers = kwargs.pop("headers", {}) or {}
        headers["X-Auth"] = DEVICE_TOKEN
        return self._with_retry(lambda: _requests_session.get(url, headers=headers, **kwargs))
    
urequests = UrequestsWrapper()

def req_update(request, device_id=None):
    """
    This allows the device to request updates from the server.
    Using this, the device can check for new messages
    """
    r = urequests.get(f"{BASE_URL}/updates?Request={request}&dev_id={device_id}")
    data = r.json()

    return data

def request_n_parse_translation(dev_id=None):
    url = f"{BASE_URL}/stt"
    with open("recording.wav", "rb") as f:
        r = urequests.post(url, files={"file": f},
                           data={"Request": "transl", "ID": dev_id},
                           headers={"X-Auth": DEVICE_TOKEN})
    print("STT status:", r.status_code)
    print("STT body:", r.text[:200])
    if r.status_code != 200:
        return ""
    try:
        data = json.loads(r.text)
    except ValueError:
        return ""
    return data.get("text", "")

def encrypt_audio(pub_key, data: bytes) -> str:
    key = os.urandom(32)
    key_as_int = int.from_bytes(key, "big")
    encrypted_key = ce.encrypt_audio_key(pub_key, key_as_int)
    cipher = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    combined = encrypted_key + cipher
    return binascii.b2a_base64(combined).decode("utf-8").strip()

def decrypt_audio(priv_key, encoded: str) -> bytes:
    d, n = priv_key
    key_size = (n.bit_length() + 7) // 8
    combined = binascii.a2b_base64(encoded)
    encrypted_key_bytes = combined[:key_size]
    cipher = combined[key_size:]
    encrypted_key_int = int.from_bytes(encrypted_key_bytes, "big")
    key_int = pow(encrypted_key_int, d, n)
    key = key_int.to_bytes(32, "big")
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(cipher))

def play_pcm(pcm_data: bytes, sample_rate=8000, percent_vol=1):
    delay_s = 1.0 / sample_rate
    percent_vol = max(0, min(1, percent_vol))
    for i in range(0, len(pcm_data) - 1, 2):
        raw_sample = int.from_bytes(pcm_data[i:i+2], "little")
        sample_8 = raw_sample >> 4
        deviation = sample_8 - 128
        scaled_deviation = int(deviation * percent_vol)
        final_sample = 128 + scaled_deviation
        pwm_speaker.duty_cycle = int(final_sample * 256)
        time.sleep(delay_s)
    pwm_speaker.duty_cycle = 0

# ______________________________________ Machine Stubs ______________________________________
class MachineMock:
    WAKEUP_ANY_HIGH = 1
    WAKEUP_ALL_LOW = 0
    def idle(self): time.sleep(0.001)
    def deepsleep(self):
        import microcontroller
        microcontroller.reset()
    def pin_sleep_wakeup(self, pins, mode):
        # Real CircuitPython deep sleep: wake when the button is pressed.
        try:
            import alarm
            triggers = []
            for p in pins:
                raw = getattr(p, "_raw_pin", None)
                pull_up = getattr(p, "_pull_up", True)
                if raw is not None:
                    p.release()  # free the DigitalInOut so the alarm can claim the pin
                    # pull-up button reads low when pressed -> wake on value=False
                    wake_value = False if pull_up else True
                    triggers.append(alarm.pin.PinAlarm(pin=raw, value=wake_value, pull=True))
            if triggers:
                alarm.exit_and_deep_sleep_until_alarms(*triggers)
        except Exception:
            import microcontroller
            microcontroller.reset()
machine = MachineMock()
#_____________________________________Processing_________________________________________

FILLER_WORDS = ["uhh", "umm", "hmm", "uh,", "um", "hm"]
def processing(converted_text, del_words=FILLER_WORDS):
    """
    This function processes all voice-to-text
    in order to reove filler words (the list FILLER_WORDS)
    """

    words = converted_text.split()

    clean_words = [w for w in words if w not in del_words] #Makes a new list of words not including the filler words present
        
    processed_words = " ".join(clean_words) #Rejoins the list of words into a string
    return processed_words
    
#_____________________________________Networking + Encryption_________________________________________
LETTERS = ["a","b","c","d","e","f","g","h","i","j","k","l","m","n","o","p","q","r","s","t","u","v","w","x","y","z"," ",
    "A","B","C","D","E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z",".",
    ",","/","[","]","`","~","\\","1","2","3","4","5","6","7","8","9","0","-","+","=","!","@","#","$","%","^","&",
    "*","(",")","<",">","?","|",";",";",":","'","\"","{","}"]

NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90"
}
DIGIT_WORDS = {v: k for k, v in NUMBER_WORDS.items()}

def toggle_digit_word(word): #Changes from number to word-number form, vice versa
    lower = word.lower()
    if lower in NUMBER_WORDS:
        return NUMBER_WORDS[lower]
    elif word in DIGIT_WORDS:
        return DIGIT_WORDS[word]
    else:
        return word 


def confirm_wifi_password(raw_text):
    """
    This is a function for confirming the wifi password
    so I don't have to keep writing this code.

    The user can edit the wifi-password that was 
    received from voice-to-text
    """
    words = raw_text.split()
    word_index = 0

    while word_index < len(words):
        word = words[word_index]
        char_index = 0
        chars = list(word)
        while char_index < len(chars):
            epd.clear(Color.WHITE)
            current_word = "".join(chars)

            #Instructions for editing the password
            epd.show_string(f"Password so far: {' '.join(words[:word_index] + [current_word])}", 5, 5)
            epd.show_string(f"Editing letter '{chars[char_index]}' in word '{word}'", 5, 13)
            epd.show_string("Up = uppercase, Down = lowercase, Select = next letter", 5, 20)
            epd.show_string("Press Send to toggle this whole word digit/word form", 5, 27)
            percent = get_percent()
            draw_battery(epd, percent, epd.width - 40, 5)
            epd.update()

            #Button code for password editing
            if up.value() == 0:
                chars[char_index] = chars[char_index].upper()
                time.sleep(0.2)
            elif down.value() == 0:
                chars[char_index] = chars[char_index].lower()
                time.sleep(0.2)
            elif select_button.value() == 0:
                char_index += 1
                time.sleep(0.2)
            elif send_mes_button.value() == 0:
                toggled = toggle_digit_word("".join(chars))
                chars = list(toggled)
                char_index = min(char_index, len(chars) - 1) if chars else 0
                time.sleep(0.2)

        words[word_index] = "".join(chars) #Joins characters into a word
        word_index = word_index + 1

    final_password = "".join(words) #Joins words into final password string
    return final_password

def record_and_confirm_text(prompt_label, dev_ID=None):
    """
    This is the function that records either the wifi
    name or the wifi password.

    It asks the user to record their response and allows
    them to edit it using the confirm_wifi_password function
    """
    while True:
        now_time = time.time()
        epd.show_string(f"Record the {prompt_label}", 50, 50)
        epd.show_string("or press UP to type", 50, 65)
        percent = get_percent()
        draw_battery(epd, percent, epd.width - 40, 5)
        epd.update()

        #Record or type
        txt = record_or_type(dev_ID, type_prompt=f"Type the {prompt_label}:")
        processed_txt = processing(txt)

        final_text = confirm_wifi_password(processed_txt) #Allows user to edit response

        epd.clear(Color.WHITE)
        epd.show_string(f"Final {prompt_label}: {final_text}", 5, 5)
        epd.show_string("Press Select to confirm, Down to start over", 5, 13)
        percent = get_percent()
        draw_battery(epd, percent, epd.width - 40, 5)
        epd.update()

        if select_button.value() == 0:
            time.sleep(0.1)
            return final_text
        elif down.value() == 0:
            time.sleep(0.1)
            continue #Restarts at the top of the loop


def choose_wifi_credentials(knownwifis=None):
    """
    This function adds a network to the wifi
    json file. If there are no known networks
    knownwifis is None and a new list is created
    """

    if knownwifis == None:
        knownwifis = []
    
    epd.clear(Color.WHITE)
    ssid = record_and_confirm_text("WiFi Name")
    password = record_and_confirm_text("Password")
    knownwifis.append((ssid, password))
    with open("wifi.json", "w") as f:
        json.dump(knownwifis, f)

def connect_to_my_wifi(ssid, password, timeout=20):
    """
    Connects to a wifi network with an automatic retry loop.
    Cleans formatting typos and prevents script crashes if connection drops.
    """
    wlan = network.WLAN(network.WLAN.IF_STA)
    wlan.active(True)
    
    # Force convert inputs to clean strings, stripping out spaces or hidden line breaks
    clean_ssid = str(ssid).strip().replace("\r", "").replace("\n", "")
    clean_password = str(password).strip().replace("\r", "").replace("\n", "")
    
    retries = 100
    for attempt in range(1, retries + 1):
        if wlan.isconnected():
            break
            
        try:
            print(f"Connecting to SSID: '{clean_ssid}' (Attempt {attempt}/{retries})...")
            wlan.connect(clean_ssid, clean_password)
            
            # Monitoring loop to check if handshake completes successfully
            start = time.time()
            while not wlan.isconnected():
                if time.time() - start > timeout:
                    raise Exception("Handshake timeout")
                time.sleep(0.5)
                
        except Exception as e:
            print(f"Attempt {attempt} failed: {e}")
            if attempt == retries:
                print("All connection attempts exhausted.")
                return "Wi-Fi connection timed out"
            time.sleep(2)  # Short pause to let the radio recover before scanning again
            
    print("Successfully connected to network!")
    return wlan

if not file_exists("wifi.json"):
    choose_wifi_credentials() #Get a new network on first boot
else:
    with open("wifi.json", "r") as f:
        known_wifis = json.load(f)
    is_connected = False
    for wifi in known_wifis: #Try to connect to each wifi
        ssid = wifi[0]
        password = wifi[1]
        connection = connect_to_my_wifi(ssid, password)
        if connection != "Wi-Fi connection timed out":
            is_connected = True
            break
    if is_connected == False:
        #Connect to a new network if none of the known networks are available
        choose_wifi_credentials(known_wifis)

# Create other json files for device info storage properly
if not file_exists("known_ids.json"):
    with open("known_ids.json", "w") as f:
        f.write("{}")

if not file_exists("my_letters.json"):
    with open("my_letters.json", "w") as f:
        f.write("[]")

if not file_exists("contacts.json"):
    with open("contacts.json", "w") as f:
        f.write("{}")

if not file_exists("history.json"):
    with open("history.json", "w") as f:
        f.write("[]")

if not file_exists("gc_username.json"):
    with open("gc_username.json", "w") as f:
        f.write('""')
    is_gc_username = False
else:
    is_gc_username = True
    with open("gc_username.json", "r") as f:
        gc_username = json.load(f)

if not file_exists("device_ID.json"):
    with open("device_ID.json", "w") as f:
        dev_ID = random.randrange(100000000, 999999999) #This is the unique device ID used when communicating with the server
        id_clear = urequests.post(f"{BASE_URL}/getID?req_ID={dev_ID}") #Confirms if ID is unique
        recv = id_clear.json()
        if recv == "Clear":
            f.write(str(dev_ID))
        else: #If the ID generated wasn't unique
            dev_ID = recv #Sets the device ID to what the server created
            f.write(recv)
else:
    with open("device_ID.json", "r") as f:
        dev_ID = f.read().strip()

#_____________________________________RSA Encryption________________________________________
"""
This is the information needed for the RSA encryption
"""
E = 65537
if not file_exists("priv_keys.json"):
    get_prime_json = urequests.post(f"{BASE_URL}/get_prime")
    whole = get_prime_json.json()
    package = whole[0].split("/")
    phi = int(package[0])
    d = int(package[1])
    n = int(package[2])
    key1 = int(package[3])
    key2 = int(package[4])

    my_pub_key = (E, n)
    my_priv_key = (d, n)

    payload = ujson.dumps({"Request": "store_pub_key", "pub_key": f"{my_pub_key[0]}/{my_pub_key[1]}", "senderID": dev_ID})
    urequests.post(f"{BASE_URL}/updates", data=payload, headers={"Content-Type": "application/json"})

    with open("priv_keys.json", "w") as f:
        json.dump(package, f)
        
else:
    with open("priv_keys.json", "r") as f:
        package = json.load(f)

        phi = int(package[0])
        d = int(package[1])
        n = int(package[2])
        key1 = int(package[3])
        key2 = int(package[4])

        my_pub_key = (E, n)
        my_priv_key = (d, n)

# Always (re)publish our public key to the server, so a failed first-boot
# store self-heals on the next boot instead of leaving us unreachable.
try:
    _pk_payload = ujson.dumps({"Request": "store_pub_key", "pub_key": f"{my_pub_key[0]}/{my_pub_key[1]}", "senderID": dev_ID})
    urequests.post(f"{BASE_URL}/updates", data=_pk_payload, headers={"Content-Type": "application/json"})
except Exception:
    pass

def encrypt_audio_key(pub_key, audio_key):
    e = pub_key[0]
    n = pub_key[1]

    encrypted_key = pow(audio_key, e, n)
    return int(encrypted_key).to_bytes((n.bit_length() + 7) // 8, "big")

#________________________________Sending/Receiving Messages________________________________

class esp_network_server:
    """
    This is the class for sending messages.

    It runs messages through the Raspberry Pi server
    to send them to the target
    """

    def __init__(self):
        self.running = True

        self.known_ids_path = "known_ids.json"
        self.known_ids = self.load_known_ids()

        self.contacts_path = "contacts.json"
        if file_exists(self.contacts_path):
            with open(self.contacts_path, "r") as f:
                self.contacts = json.load(f)
        else:
            self.contacts = {}

        self.message_to_send = ""

    def load_known_ids(self): #Unknown ids get new letters, so, the device logs the ones it knows
        #Load known ids properly
        if file_exists(self.known_ids_path):
            try:
                with open(self.known_ids_path, "r") as f:
                    return json.load(f)
            except:
                return {}
        else:
            return {}
        
    def run(self, get_message, target_id, contact):
        self.clients = {}
        self.target_id = target_id

        while self.running:
            # known_ids is saved as JSON, whose keys are always strings, so
            # use a string form of the id for all known_ids lookups/stores.
            tid = str(self.target_id)
            
            #Each known ID gets its own Letters for ciphering
            self.clients[self.target_id] = {
                "letters": LETTERS
            }

            if tid not in self.known_ids: #New device logic

                epd.clear(Color.WHITE)
                wrap_text(epd, f"New device: {self.target_id}. Enter a contact name: ", 20, 20)
                percent = get_percent()
                draw_battery(epd, percent, epd.width - 40, 5)
                epd.update()
                time.sleep(0.1)
                while True:
                    wrap_text(epd, "Record name, or UP to type", 20, 40)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()

                    typed = None
                    chose = False
                    while not chose:
                        if record_button.value() == 0:
                            chose = True   # fall through to voice recording
                        elif up.value() == 0:
                            typed = text_entry("Type contact name:")
                            chose = True
                        machine.idle()

                    if typed is not None:
                        contact_name_str = typed
                    else:
                        # existing voice path:
                        now_time = time.time()
                        while time.time() - now_time < 60:
                            if record_button.value() == 0:
                                samples = []
                                while record_button.value() == 0:
                                    samples = collect_audio(samples)
                                with open(FILENAME, "wb") as f:
                                    write_wav_header(f, len(samples) * 2)
                                    for s in samples:
                                        f.write(s)
                                break
                        txt = request_n_parse_translation(dev_ID)
                        contact_name_str = processing(txt)
                    epd.clear(Color.WHITE)
                    time.sleep(0.1)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    wrap_text(epd, f"Set contact to {contact_name_str}?", 10, 10)
                    epd.update()
                    time.sleep(0.1)
                    wrap_text(epd, "Press 'Select' to Confirm", 20, 20)
                    wrap_text(epd, "Press 'Down' to Try Again", 30, 30)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
                    
                    # FIX: Wait loop + uses select_button to match the prompt instead of up
                    confirmed = False
                    while True:
                        if select_button.value() == 0:
                            confirmed = True
                            break
                        elif down.value() == 0:
                            confirmed = False
                            break
                        time.sleep(0.05)
                    
                    if confirmed:
                        time.sleep(0.1)
                        epd.clear(Color.WHITE)
                        break
                    else:
                        epd.clear(Color.WHITE)
                        continue

                name_ = contact_name_str
                self.contacts[name_] = self.target_id

                with open(self.contacts_path, "w") as f:
                    json.dump(self.contacts, f)

                #First time this id connects, give their key
                shuffle_in_place(LETTERS)
                self.known_ids[tid] = LETTERS.copy()

                # Send alphabet
                alph = json.dumps(self.known_ids[tid])
                payload = ujson.dumps({"msg": alph, "destinationID": self.target_id, "senderID": dev_ID, "type": "key_exchange"})
                send = urequests.post(f"{BASE_URL}/send-msg",
                               data=payload,
                               headers={"Content-Type": "application/json"})

                # Save updated known_ids
                with open(self.known_ids_path, "w") as f:
                    json.dump(self.known_ids, f)

            client_letters = self.known_ids[tid]

            self.clients[self.target_id] = {
                "letters": client_letters
            }

            
            while self.running:

                #Send encrypted message
                message = get_message()
                
                target = self.clients.get(self.target_id)

                letters = target["letters"]

                new_message, sent_key = ce.cipher(message, alphabet=letters)
                combined_message = sent_key + new_message
                epd.clear(Color.WHITE)
                
                #Save Message to History
                if file_exists("history.json"):
                    with open("history.json", "r") as f:
                        try:
                            history = json.load(f)
                        except:
                            history = []
                else:
                    history = []
                
                history.append({"To" : contact, "ID" : target_id, "Time" : time.time(), "Message" : message, "Cencrypted Message" : combined_message})
                with open("history.json", "w") as f:
                    json.dump(history, f)
            
                epd.show_string("Sending...", 20, 20)
                percent = get_percent()
                draw_battery(epd, percent, epd.width - 40, 5)
                epd.update()
                #Prepare and send message
                payload = ujson.dumps({"msg": combined_message, "destinationID": self.target_id, "senderID": dev_ID, "type": "txt"})
                urequests.post(f"{BASE_URL}/send-msg", #Send message to server
                               data=payload,
                               headers={"Content-Type": "application/json"})
                
                time.sleep(0.5)
                epd.clear(Color.WHITE)
                epd.show_string("Sent", 20, 20)
                percent = get_percent()
                draw_battery(epd, percent, epd.width - 40, 5)
                epd.update()                
                time.sleep(0.5)
                self.running = False



class esp_network_client:
    """
    This is the class that receives messages.

    It checks its 'Mailbox' in the server to 
    see if there are any messages for it.

    This handles text messages as well as voice messages
    """

    def __init__(self):
        self.running = True
        
    
    def client(self, out_message, percent_vol):
        try:
            if file_exists("my_letters.json"):
                with open("my_letters.json", "r") as f:
                    data = f.read().strip()
                    if data:
                        LETTERS = json.loads(data)
                    else:
                        LETTERS = None
                
            if file_exists("device_ID.json"):
                with open("device_ID.json", "r") as f:
                    data = f.read().strip()
                    my_id = json.loads(data)
            
            epd.clear(Color.WHITE)
            wrap_text(epd, "Waiting for messages. Press record to go back.", 20, 20)
            epd.update()

            while self.running:
                if record_button.value() == 0:
                    time.sleep(0.2)
                    self.running = False
                    break
                msgs = req_update("check_mail", my_id)

                with open("contacts.json", "r") as f:
                     my_contacts = json.load(f)
                
                for item in msgs:
                    dest = item["destinationID"]
                    d_msg = item["msg"]
                    sender_ID = item["senderID"]
                    msg_type = item["type"] #Extract message type from server return

                    for key, value in my_contacts.items():
                        if str(value) == str(sender_ID):
                            cont_name = key
                            break

                    else:
                        cont_name = sender_ID
                    
                    #Handle different message types
                    if msg_type == "txt":
                        true_message = ce.decipher(d_msg, alphabet=LETTERS)
                        notif_chime(percent_vol=percent_vol)
                        out_message(true_message, cont_name)
                        # Save received message to history
                        if file_exists("history.json"):
                            with open("history.json", "r") as f:
                                try:
                                    hist = json.load(f)
                                except:
                                    hist = []
                        else:
                            hist = []
                        hist.append({"From": cont_name, "ID": sender_ID, "Time": time.time(), "Message": true_message})
                        with open("history.json", "w") as f:
                            json.dump(hist, f)
                        time.sleep(2)
                    elif msg_type == "audio":
                        deciphered_audio = decrypt_audio(my_priv_key, d_msg)
                        epd.clear(Color.WHITE)
                        wrap_text(epd, f"Voice message from {cont_name}:")
                        epd.update()
                        time.sleep(0.75)
                        play_pcm(deciphered_audio, percent_vol=percent_vol)
                        time.sleep(2)
                    elif msg_type == "key_exchange":
                        with open("my_letters.json", "w") as f:
                            json.dump(json.loads(d_msg), f)

                # brief pause between polls; also keeps the exit button responsive
                for _ in range(10):
                    if record_button.value() == 0:
                        break
                    time.sleep(0.1)
                
        except:
            return None



#_____________________________________________Main__________________________________________________

def wrap_text(epd, text, x, y, max_width=250, font_width=6, line_height=10):
    """
    Helper function that wraps text so that it doesn't 
    get cut off on the e-ink display
    """

    max_chars = max_width // font_width
    words = text.split()
    line = ""
    lines = []

    for word in words:
        if len(line + word) <= max_chars:
            line += word + " "
        else:
            lines.append(line)
            line = word + " "
    lines.append(line)

    #Draw each line
    for i, ln in enumerate(lines):
        epd.show_string(ln, x, y + i * line_height)

"""
get_processed_message and use_message are both helper functions
used by the send/receive classes
"""
def get_processed_message():
    return processed_txt

def use_message(decoded_msg, sender):
    epd.clear(Color.WHITE)
    wrap_text(epd, f"Message from {sender}: {decoded_msg}", 20, 20)
    percent = get_percent()
    draw_battery(epd, percent, epd.width - 40, 5)
    epd.update()

def render_block_text(text, width, height): #Creates block text art
    #5x7 block font for A–Z and 0–9
    FONT = {
        "A": ["01110",
              "10001",
              "10001",
              "11111",
              "10001",
              "10001",
              "10001"],
        "B": ["11110",
              "10001",
              "11110",
              "10001",
              "10001",
              "10001",
              "11110"],
        "C": ["01111",
              "10000",
              "10000",
              "10000",
              "10000",
              "10000",
              "01111"],
        "D": ["11110",
              "10001",
              "10001",
              "10001",
              "10001",
              "10001",
              "11110"],
        "E": ["11111",
              "10000",
              "11110",
              "10000",
              "10000",
              "10000",
              "11111"],
        "F": ["11111",
              "10000",
              "11110",
              "10000",
              "10000",
              "10000",
              "10000"],
        "G": ["01111",
              "10000",
              "10000",
              "10111",
              "10001",
              "10001",
              "01111"],
        "H": ["10001",
              "10001",
              "10001",
              "11111",
              "10001",
              "10001",
              "10001"],
        "I": ["11111",
              "00100",
              "00100",
              "00100",
              "00100",
              "00100",
              "11111"],
        "J": ["11111",
              "00010",
              "00010",
              "00010",
              "10010",
              "10010",
              "01100"],
        "K": ["10001",
              "10010",
              "10100",
              "11000",
              "10100",
              "10010",
              "10001"],
        "L": ["10000",
              "10000",
              "10000",
              "10000",
              "10000",
              "10000",
              "11111"],
        "M": ["10001",
              "11011",
              "10101",
              "10101",
              "10001",
              "10001",
              "10001"],
        "N": ["10001",
              "11001",
              "10101",
              "10011",
              "10001",
              "10001",
              "10001"],
        "O": ["01110",
              "10001",
              "10001",
              "10001",
              "10001",
              "10001",
              "01110"],
        "P": ["11110",
              "10001",
              "10001",
              "11110",
              "10000",
              "10000",
              "10000"],
        "Q": ["01110",
              "10001",
              "10001",
              "10001",
              "10101",
              "10010",
              "01101"],
        "R": ["11110",
              "10001",
              "10001",
              "11110",
              "10100",
              "10010",
              "10001"],
        "S": ["01111",
              "10000",
              "10000",
              "01110",
              "00001",
              "00001",
              "11110"],
        "T": ["11111",
              "00100",
              "00100",
              "00100",
              "00100",
              "00100",
              "00100"],
        "U": ["10001",
              "10001",
              "10001",
              "10001",
              "10001",
              "10001",
              "01110"],
        "V": ["10001",
              "10001",
              "10001",
              "10001",
              "01010",
              "01010",
              "00100"],
        "W": ["10001",
              "10001",
              "10001",
              "10101",
              "10101",
              "11011",
              "10001"],
        "X": ["10001",
              "01010",
              "00100",
              "00100",
              "00100",
              "01010",
              "10001"],
        "Y": ["10001",
              "01010",
              "00100",
              "00100",
              "00100",
              "00100",
              "00100"],
        "Z": ["11111",
              "00001",
              "00010",
              "00100",
              "01000",
              "10000",
              "11111"],
        "0": ["01110",
              "10001",
              "10011",
              "10101",
              "11001",
              "10001",
              "01110"],
        "1": ["00100",
              "01100",
              "00100",
              "00100",
              "00100",
              "00100",
              "01110"],
        "2": ["01110",
              "10001",
              "00001",
              "00010",
              "00100",
              "01000",
              "11111"],
        "3": ["11110",
              "00001",
              "00001",
              "01110",
              "00001",
              "00001",
              "11110"],
        "4": ["00010",
              "00110",
              "01010",
              "10010",
              "11111",
              "00010",
              "00010"],
        "5": ["11111",
              "10000",
              "10000",
              "11110",
              "00001",
              "00001",
              "11110"],
        "6": ["01110",
              "10000",
              "10000",
              "11110",
              "10001",
              "10001",
              "01110"],
        "7": ["11111",
              "00001",
              "00010",
              "00100",
              "01000",
              "01000",
              "01000"],
        "8": ["01110",
              "10001",
              "10001",
              "01110",
              "10001",
              "10001",
              "01110"],
        "9": ["01110",
              "10001",
              "10001",
              "01111",
              "00001",
              "00001",
              "01110"],
    }

    #Build raw 7-row text pattern
    rows = [[] for _ in range(7)]
    for ch in text:
        pattern = FONT.get(ch.upper(), ["00000"] * 7)
        for i in range(7):
            rows[i] += [int(x) for x in pattern[i]] + [0]  #1-pixel spacing

    #Scale uniformly to preserve aspect ratio
    scale = max(1, min(width // len(rows[0]), height // len(rows)))
    scale_x = scale
    scale_y = scale

    bitmap = []
    for row in rows:
        scaled_row = []
        for pixel in row:
            scaled_row += [pixel] * scale_x
        for _ in range(scale_y):
            bitmap.append(scaled_row[:width])  #trim to exact width

    return bitmap[:height]  #trim to exact height

icons = {
    "history": [
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,1,1,1,0,0,0,0,0,0,0,0,0,0,1,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0],
        [0,0,0,0,0,1,1,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0],
        [0,0,0,0,1,1,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0],
        [0,0,0,0,1,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0],
        [0,0,0,1,1,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0],
        [0,0,0,1,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0],
        [0,0,1,1,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0],
        [0,0,1,1,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0],
        [0,0,1,1,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,0,0,0,0,0,0,0,0,0,1,1,0,0],
        [0,0,1,1,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,0,0,1,1,0,0],
        [0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,1,1,0,1,1,1,1,0,0,0,0,0,0,1,1,0,0],
        [0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0],
        [0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0],
        [0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0],
        [0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0],
        [0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0],
        [0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0],
        [0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0],
        [0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,1,1,1,0,0,0,0,0,0,0,0,0,0,1,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    ],
    "Contacts": [
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0],
        [0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    ],
    "settings": [
        [0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,0,0,0,0,1,1,1,1,1,0,0,0,0,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,0,0,0,0,1,1,1,1,1,1,0,0,0,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,0,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,0,0,0,0,1,1,1,1,1,1,0,0,0,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    ],
    "gc_icon": [
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0],
        [0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0],
        [0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0],
        [0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0],
        [0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0],
        [0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0],
        [0,0,1,0,0,0,0,1,1,1,0,0,0,0,1,1,1,0,0,0,0,1,1,1,0,0,0,0,0,1,0,0],
        [0,0,1,0,0,0,0,1,1,1,0,0,0,0,1,1,1,0,0,0,0,1,1,1,0,0,0,0,0,1,0,0],
        [0,0,1,0,0,0,0,1,1,1,0,0,0,0,1,1,1,0,0,0,0,1,1,1,0,0,0,0,0,1,0,0],
        [0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0],
        [0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0],
        [0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0],
        [0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0],
        [0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0],
        [0,0,0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,0,0,0,0],
        [0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    ],
    "Up": [
        [0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,1,1,0,0,0,0,0,0],
        [0,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,0,1,1,0,0,1,1,0,0,1,1,0,0,0],
        [0,0,1,0,0,0,1,1,0,0,0,0,1,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    ],
    "Down": [
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0],
        [0,0,1,0,0,0,1,1,0,0,0,0,1,0,0,0],
        [0,0,0,1,1,0,0,1,1,0,0,1,1,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,1,1,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    ],
    "Volume": [
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0],
        [0,0,0,0,0,0,1,1,1,0,1,0,1,0,0,0],
        [0,0,0,0,0,1,1,1,1,0,1,0,0,1,0,0],
        [0,0,0,0,1,1,1,1,1,0,1,0,1,0,1,0],
        [0,0,0,1,1,1,1,1,1,0,1,0,1,0,0,1],
        [0,0,0,1,1,1,1,1,1,0,1,0,1,0,1,0],
        [0,0,0,1,1,1,1,1,1,0,1,0,1,0,0,1],
        [0,0,0,1,1,1,1,1,1,0,1,0,1,0,1,0],
        [0,0,0,0,1,1,1,1,1,0,1,0,1,0,0,1],
        [0,0,0,0,0,1,1,1,1,0,1,0,1,0,1,0],
        [0,0,0,0,0,0,1,1,1,0,1,0,0,1,0,0],
        [0,0,0,0,0,0,0,0,0,0,1,0,1,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    ],
    "Reset": [
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,0,0,1,0,0],
        [0,0,1,1,0,0,0,0,0,0,0,1,1,1,0,0],
        [0,1,0,0,0,0,0,0,0,0,0,0,1,1,0,0],
        [0,1,0,0,0,0,0,0,0,0,0,0,0,1,0,0],
        [1,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0],
        [1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,0,0,0,0,0,0,0,0,0,0,0,1,0,0],
        [0,0,1,0,0,0,0,0,0,0,0,0,1,0,0,0],
        [0,0,1,1,0,0,0,0,0,0,0,1,1,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    ],
    "send_icon": [
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,0],
        [0,0,0,0,0,0,0,0,0,1,1,0,0,0,1,0],
        [0,0,0,0,0,0,0,1,1,0,0,0,0,1,1,0],
        [0,0,0,0,0,1,1,0,0,0,0,0,1,0,1,0],
        [0,0,0,1,1,0,0,0,0,0,0,1,0,0,1,0],
        [0,1,1,0,0,0,0,0,0,0,1,0,0,0,1,0],
        [1,1,1,0,0,0,0,0,0,1,0,0,0,0,1,0],
        [0,1,1,0,0,0,0,0,0,0,1,0,0,0,1,0],
        [0,0,0,1,1,0,0,0,0,0,0,1,0,0,1,0],
        [0,0,0,0,0,1,1,0,0,0,0,0,1,0,1,0],
        [0,0,0,0,0,0,0,1,1,0,0,0,0,1,1,0],
        [0,0,0,0,0,0,0,0,0,1,1,0,0,0,1,0],
        [0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0],
    ],
}

def invert(bitmap):
    """
    Returns a NEW inverted copy of a bitmap without modifying the original.
    (The original in-place version corrupted the source icons.)
    """
    return [[1 - px for px in row] for row in bitmap]
    
inverted_icons = {
    "inv_settings" : invert(icons["settings"]),
    "inv_hist" : invert(icons["history"]),
    "inv_contacts" : invert(icons["Contacts"]),
    "inv_vol" : invert(icons["Volume"]),
    "inv_reset" : invert(icons["Reset"]),
    "inv_gc" : invert(icons["gc_icon"]),
    "inc_send" : invert(icons["send_icon"])
}

def UI(epd=epd, icons=icons, inverted_icons=inverted_icons):
    """
    Main menu. E-ink friendly: the panel is only refreshed when the
    selection actually changes, so no continuous refresh loop.
    """
    # icon key, and (x, y) for each selectable position, indexed by selection number
    positions = {
        0: ("history",  "inv_hist",     12,  86),
        1: ("Contacts", "inv_contacts", 109, 86),
        2: ("settings", "inv_settings", 206, 86),
        3: ("gc_icon",  "inv_gc",       90,  6),
    }

    def draw(selection):
        epd.clear(Color.WHITE)
        # draw every icon normally; mark the selected one with a border box
        for idx, (icon_key, inv_key, ix, iy) in positions.items():
            epd.show_bitmap(icons[icon_key], ix, iy)
            if idx == selection:
                # box around the selected icon (icons are 32x32 or smaller)
                bmp = icons[icon_key]
                ih = len(bmp)
                iw = len(bmp[0]) if ih else 0
                pad = 3
                epd.draw_rectangle(ix - pad, iy - pad, ix + iw + pad, iy + ih + pad)
        percent = get_percent()
        draw_battery(epd, percent, epd.width - 40, 5)
        epd.update()

    selection = 0
    last_drawn = None
    idle_time = time.time()

    while select_button.value() != 0 and send_mes_button.value() != 0 and shut_off.value() != 0:
        # Only touch the panel when the highlighted icon changed
        if selection != last_drawn:
            draw(selection)
            last_drawn = selection

        moved = False
        if up.value() == 0:
            selection = selection + 1 if selection < 3 else 0
            moved = True
        elif down.value() == 0:
            selection = selection - 1 if selection > 0 else 3
            moved = True
        elif send_mes_button.value() == 0:
            selection = 4
            time.sleep(0.2)
            break

        if moved:
            idle_time = time.time()   # activity resets the idle timer
            time.sleep(0.25)          # debounce the button
        else:
            machine.idle()            # sleep the CPU while waiting for input

        if time.time() - idle_time >= 60:
            return 5

    if send_mes_button.value() == 0:
        selection = 4
        time.sleep(0.1)
    
    # Handle power management safely
    percent = get_percent()
    if shut_off.value() == 0:
        epd.clear(Color.WHITE)
        epd.show_string(f"Press Power to Wake", 30, 50)
        epd.update()
        time.sleep(2)
        shut_off_chime(percent_vol=percent_vol)
        time.sleep(0.2)
        while True:
            machine.pin_sleep_wakeup([shut_off], machine.WAKEUP_ANY_HIGH)
            machine.deepsleep()
            if shut_off.value() == 0:
                break
                
    elif percent < 45:
        epd.clear(Color.WHITE)
        epd.show_string(f"Charge The Device, it is at {int(percent)}%", 30, 30)
        epd.update()
        time.sleep(2)
        while percent < 60:
            percent = get_percent()
            epd.clear(Color.WHITE)
            epd.show_string(f"Charge The Device, it is at {int(percent)}%", 30, 30)
            epd.update()
            time.sleep(5) # Slow checking when charging to save CPU
            machine.idle()

    return selection

def gc_UI(is_full):
    """
    This is the UI for the group chat
    since the group chat has its own
    selections
    """
    x_left  = 3
    x_right = 234
    y_mid   = 54
    x_mid = 119
    selection = 0
    if is_full == True:
        epd.clear()
        epd.show_bitmap(icons["history"], x_left, y_mid)
        epd.show_bitmap(icons["send_icon"], x_right, y_mid)
        epd.update()
        while select_button.value() != 0:
            percent = get_percent()
            draw_battery(epd, percent, epd.width - 40, 5)
            epd.update()

            if selection == 1:
                epd.show_bitmap(inverted_icons["inc_send"], 239, 111)
                epd.update()
                time.sleep(0.2)
                epd.show_bitmap(icons["send_icon"], 239, 111)
                epd.update()
            elif selection == 0:
                epd.show_bitmap(inverted_icons["inv_hist"], 120, 110)
                epd.update()
                time.sleep(0.2)
                epd.show_bitmap(icons["history"], 120, 110)
                epd.update()
            
            if up.value() == 0 and selection < 1:
                selection = selection + 1
                time.sleep(0.4)
            elif down.value() == 0 and selection > 0:
                selection = selection - 1
                time.sleep(0.4)
            #Exceptions
            elif up.value() == 0 and selection >= 1:
                selection = 0
                time.sleep(0.4)
            elif down.value() == 0 and selection <= 0:
                selection = 1
                time.sleep(0.4)
        return selection
    
    else:
        epd.show_string("Press 'Record' to go back", 20, 20)

        epd.update()
        time.sleep(1.5)
        epd.clear(Color.WHITE)
        epd.show_bitmap(icons["send_icon"], x_mid, y_mid)
        epd.update()
        while select_button.value() != 0 and record_button.value() != 0:
            percent = get_percent()
            draw_battery(epd, percent, epd.width - 40, 5)
            epd.update()

            if selection == 0:
                epd.show_bitmap(inverted_icons["inc_send"], 239, 111)
                epd.update()
                time.sleep(0.2)
                epd.show_bitmap(icons["send_icon"], 239, 111)
                epd.update()
        
        if record_button.value() == 0:
            time.sleep(0.1)
            epd.clear(Color.WHITE)
            return None

#Opening Screen
handcryption_bitmap = render_block_text("HANDCRYPTION", 220, 30)
recording_bitmap = render_block_text("RECORDING", 220, 30)
tap_bitmap = render_block_text("Press a Button to Continue", 240, 30)
x_start = (epd.width - 220) // 2
y_start = (epd.height - 30) // 2

percent_vol = 1 #Volume is originally 100%
print("A: about to show opening screen")
epd.show_bitmap(handcryption_bitmap, x_start, y_start)
epd.update()
print("B: opening screen refreshed")
percent = get_percent()
draw_battery(epd, percent, epd.width - 40, 5)
handcryption_chime(percent_vol=percent_vol)
print("C: chime done")

gc_username = None
is_past_msg_sent = False

time.sleep(2)
print("D: entering main loop")

while True:
    try:
        epd.clear(Color.WHITE)
        time.sleep(2)
        print("E: drawing tap prompt")
        epd.show_bitmap(tap_bitmap, x_start, y_start)
        epd.update()
        time.sleep(0.75)
        print("F: tap prompt refresh returned")
        while select_button.value() == 1 and down.value() == 1 and up.value() == 1 and send_mes_button.value() == 1 and record_button.value() == 1:
            machine.idle()
        print("G: button pressed, waking")

        wake_chime(percent_vol=percent_vol)
        epd.clear(Color.WHITE)
        time.sleep(0.75)
        percent = get_percent()
        draw_battery(epd, percent, epd.width - 40, 5)
        epd.update()
        time.sleep(1)
        
        u_select = UI()
        
        if u_select == 4: #Send Message
            epd.clear(Color.WHITE)
            #Choose who to send it to
            with open("contacts.json", "r") as f:
                contacts = json.load(f)
        
            contact_list = []
            for name in contacts:
                contact_list.append(name)

            cont_num = 0
            last_cont_num = None
            
            while select_button.value() != 0:
                if cont_num != last_cont_num: # Only redraw if selection changed
                    epd.clear(Color.WHITE)
                    if len(contact_list) > 0:
                        epd.show_string("Send to:", 20, 10)
                        epd.show_string(contact_list[cont_num], 20, 45)
                        epd.show_string("select=ok  record=back", 20, 100)
                    else:
                        wrap_text(epd, "No contacts yet. Press record to go make one.", 20, 30)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
                    last_cont_num = cont_num
                
                if record_button.value() == 0:
                    time.sleep(0.07)
                    cont_num = None
                    break
                    
                if len(contact_list) > 0:
                    if down.value() == 0 and cont_num < (len(contact_list) - 1):
                        cont_num += 1
                        time.sleep(0.2)
                    elif up.value() == 0 and cont_num > 0:
                        cont_num -= 1
                        time.sleep(0.2)
                    elif up.value() == 0 and cont_num == 0:
                        cont_num = (len(contact_list) - 1)
                        time.sleep(0.2)
                    elif down.value() == 0 and cont_num == (len(contact_list) - 1):
                        cont_num = 0
                        time.sleep(0.2)
                machine.idle()

            if cont_num == None:
                u_select = 1
                continue

            epd.clear(Color.WHITE)
            wrap_text(epd, "Do you want to send in text (up) or voice (down)?", 20, 20)
            epd.update()
            sel = None
            while sel == None:
                if up.value() == 0:
                    sel = 0
                    time.sleep(0.1)
                elif down.value() == 0:
                    sel = 1
                    time.sleep(0.1)
                machine.idle()
                
            if sel == 0:
                epd.clear(Color.WHITE)
                wrap_text(epd, "Record message, or UP to type", 20, 40)
                percent = get_percent()
                draw_battery(epd, percent, epd.width - 40, 5)
                epd.update()

                typed = None
                chose = False
                while not chose:
                    if record_button.value() == 0:
                        chose = True   # fall through to voice recording
                    elif up.value() == 0:
                        typed = text_entry("Type message:")
                        chose = True
                    machine.idle()

                if typed is not None:
                    message_str = typed
                else:
                    # existing voice path:
                    now_time = time.time()
                    while time.time() - now_time < 60:
                        if record_button.value() == 0:
                            samples = []
                            while record_button.value() == 0:
                                samples = collect_audio(samples)
                            with open(FILENAME, "wb") as f:
                                write_wav_header(f, len(samples) * 2)
                                for s in samples:
                                    f.write(s)
                            break
                        
                    txt = request_n_parse_translation(dev_ID)
                    message_str = processing(txt)

                processed_txt = message_str
                epd.clear(Color.WHITE)
                wrap_text(epd, f"Message: {message_str}", 10, 10)
                wrap_text(epd, "Press 'UP' to Confirm the message, 'DOWN' to Try Again", 10, 50)
                percent = get_percent()
                draw_battery(epd, percent, epd.width - 40, 5)
                epd.update()
                        
                waiting = True
                while waiting:
                    if up.value() == 0:
                        time.sleep(0.1)
                        epd.clear(Color.WHITE)
                        rec = False
                        waiting = False
                    elif down.value() == 0:
                        epd.clear(Color.WHITE)
                        waiting = False
                    machine.idle()

            else:
                now_time = time.time()
                rec = True
                while time.time() - now_time < 60 and rec == True:
                    epd.clear(Color.WHITE)
                    wrap_text(epd, "Hold the 'Record' button to record a message", 20, 20)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
                    
                    if record_button.value() == 0:
                        epd.clear(Color.WHITE)
                        epd.show_bitmap(recording_bitmap, x_start, y_start)
                        percent = get_percent()
                        draw_battery(epd, percent, epd.width - 40, 5)
                        epd.update()

                        samples = []
                        while record_button.value() == 0:
                            samples = collect_audio(samples)
                        
                        with open(FILENAME, "wb") as f:
                            write_wav_header(f, len(samples) * 2)
                            for s in samples:
                                f.write(s)
                        rec = False # Break out to send
                        
                with open(FILENAME, "rb") as f:
                    audio_bytes = f.read()

                pcm_data = audio_bytes[44:]
    
            if sel == 0:
                target_name = contact_list[cont_num]
                target_id = contacts[target_name]
                device = esp_network_server()
                device.run(get_processed_message, target_id, target_name)
            elif sel == 1:
                target_name = contact_list[cont_num]
                target_id = contacts[target_name]
                payload = ujson.dumps({"Request": "get_cont_pub_key", "targ_id": target_id})
                cli_pub_key_data = urequests.post(f"{BASE_URL}/updates",
                               data=payload,
                               headers={"Content-Type": "application/json"})
                cli_pub_key_data = cli_pub_key_data.json()
                if "e" not in cli_pub_key_data or "n" not in cli_pub_key_data:
                    epd.clear(Color.WHITE)
                    wrap_text(epd, "No encryption key on file for this contact. They need to connect first.", 20, 20)
                    epd.update()
                    time.sleep(3)
                else:
                    cli_pub_key = (cli_pub_key_data["e"], cli_pub_key_data["n"])
                    encrypted_audio_to_send = encrypt_audio(cli_pub_key, pcm_data)
                    payload = ujson.dumps({"msg": encrypted_audio_to_send, "type": "audio", "destinationID" : target_id, "senderID" : dev_ID})
                    send = urequests.post(f"{BASE_URL}/send-msg",
                                   data=payload,
                                   headers={"Content-Type": "application/json"})
                
        elif u_select == 0: #Message history
            DEL_CHARS = ["{", "}", "[", "]"]
            if file_exists("history.json"):
                with open("history.json", "r") as f:
                    try:
                        history = json.load(f)
                        if len(history) == 0:
                            raise ValueError("Empty History")
                            
                        epd.clear(Color.WHITE)
                        epd.show_string("Press 'Record' to go back", 20, 20)
                        epd.update()
                        time.sleep(3)
                        
                        hist_num = 0
                        last_hist_num = None
                        
                        while record_button.value() != 0:
                            if hist_num != last_hist_num:
                                epd.clear(Color.WHITE)
                                epd.draw_rectangle(7, 7, 243, 115)
                                entry = history[hist_num]
                                if "From" in entry:
                                    header = "From: " + str(entry.get("From", "?"))
                                else:
                                    header = "To: " + str(entry.get("To", "?"))
                                body = str(entry.get("Message", ""))
                                epd.show_string(header, 16, 12)
                                wrap_text(epd, body, 16, 32)
                                
                                if hist_num > 0 and hist_num < len(history) - 1:
                                    epd.show_bitmap(icons["Up"], 9, 9)
                                    epd.show_bitmap(icons["Down"], 256, 108)
                                elif hist_num == 0:
                                    epd.show_bitmap(icons["Down"], 256, 108)
                                else:
                                    epd.show_bitmap(icons["Up"], 9, 9)
                                epd.update()
                                last_hist_num = hist_num

                            if up.value() == 0 and hist_num < (len(history) - 1):
                                hist_num += 1
                                time.sleep(0.2)
                            elif down.value() == 0 and hist_num > 0:
                                hist_num -= 1
                                time.sleep(0.2)
                            elif up.value() == 0 and hist_num >= (len(history) - 1):
                                hist_num = 0
                                time.sleep(0.2)
                            elif down.value() == 0 and hist_num == 0:
                                hist_num = len(history) - 1
                                time.sleep(0.2)
                            machine.idle()
                            
                    except:
                        epd.clear(Color.WHITE)
                        wrap_text(epd, "Sorry, you have no current history. Send a message to start saving history", 20, 20)
                        epd.update()
                        time.sleep(2)
            else:
                epd.clear(Color.WHITE)
                wrap_text(epd, "Sorry, you have no current history. Send a message to start saving history", 20, 20)
                epd.update()
                time.sleep(2)

        elif u_select == 1: #Contacts
            epd.clear(Color.WHITE)
            DEL_CHARS = ["{", "}", "[", "]"]
            if file_exists("contacts.json") and os.stat("contacts.json")[6] > 0:
                with open("contacts.json", "r") as f:
                    try:
                        stored_contacts = list(json.load(f).keys())
                        if len(stored_contacts) == 0:
                            raise ValueError("Empty")
                            
                        epd.show_string("Press 'Record' to go back", 20, 20)
                        epd.update()
                        time.sleep(1.3)
                        
                        cont_num = 0
                        last_cont_num = None
                        
                        while record_button.value() != 0:
                            if cont_num != last_cont_num:
                                epd.clear(Color.WHITE)
                                epd.draw_rectangle(7, 7, 243, 115)
                                wrap_text(epd, processing(f"{stored_contacts[cont_num]}", del_words=DEL_CHARS), 16, 12)
                                
                                if cont_num > 0 and cont_num < len(stored_contacts) - 1:
                                    epd.show_bitmap(icons["Up"], 9, 9)
                                    epd.show_bitmap(icons["Down"], 256, 108)
                                elif cont_num == 0:
                                    epd.show_bitmap(icons["Down"], 256, 108)
                                else:
                                    epd.show_bitmap(icons["Up"], 9, 9)
                                epd.update()
                                last_cont_num = cont_num

                            if up.value() == 0 and cont_num < (len(stored_contacts) - 1):
                                cont_num += 1
                                time.sleep(0.2)
                            elif down.value() == 0 and cont_num > 0:
                                cont_num -= 1
                                time.sleep(0.2)
                            elif up.value() == 0 and cont_num >= (len(stored_contacts) - 1):
                                cont_num = 0
                                time.sleep(0.2)
                            elif down.value() == 0 and cont_num == 0:
                                cont_num = len(stored_contacts) - 1
                                time.sleep(0.2)
                            machine.idle()

                    except Exception:
                        contacts = {}
                        epd.clear(Color.WHITE)
                        wrap_text(epd, "Create a contact", 20, 20)
                        percent = get_percent()
                        draw_battery(epd, percent, epd.width - 40, 5)
                        epd.update()
                        time.sleep(1)
                        
                        creating_contact = True
                        while creating_contact:
                            wrap_text(epd, "Record name, or UP to type", 20, 40)
                            percent = get_percent()
                            draw_battery(epd, percent, epd.width - 40, 5)
                            epd.update()

                            typed = None
                            chose = False
                            while not chose:
                                if record_button.value() == 0:
                                    chose = True   # fall through to voice recording
                                elif up.value() == 0:
                                    typed = text_entry("Type contact name:")
                                    chose = True
                                machine.idle()

                            if typed is not None:
                                contact_name_str = typed
                            else:
                                # existing voice path:
                                now_time = time.time()
                                while time.time() - now_time < 60:
                                    if record_button.value() == 0:
                                        samples = []
                                        while record_button.value() == 0:
                                            samples = collect_audio(samples)
                                        with open(FILENAME, "wb") as f:
                                            write_wav_header(f, len(samples) * 2)
                                            for s in samples:
                                                f.write(s)
                                        break
                                    
                                txt = request_n_parse_translation(dev_ID)
                                contact_name_str = processing(txt)

                            epd.clear(Color.WHITE)
                            wrap_text(epd, "Record ID, or UP to type", 20, 40)
                            percent = get_percent()
                            draw_battery(epd, percent, epd.width - 40, 5)
                            epd.update()

                            typed = None
                            chose = False
                            while not chose:
                                if record_button.value() == 0:
                                    chose = True   # fall through to voice recording
                                elif up.value() == 0:
                                    typed = text_entry("Type contact ID:")
                                    chose = True
                                machine.idle()

                            if typed is not None:
                                cl_id = typed
                            else:
                                # existing voice path:
                                now_time = time.time()
                                while time.time() - now_time < 60:
                                    if record_button.value() == 0:
                                        samples = []
                                        while record_button.value() == 0:
                                            samples = collect_audio(samples)
                                        with open(FILENAME, "wb") as f:
                                            write_wav_header(f, len(samples) * 2)
                                            for s in samples:
                                                f.write(s)
                                        break
                                txt = request_n_parse_translation(dev_ID)
                                cl_id = processing(txt)
                                
                            epd.clear(Color.WHITE)
                            time.sleep(0.1)
                            percent = get_percent()
                            draw_battery(epd, percent, epd.width - 40, 5)
                            wrap_text(epd, f"Set ID to {cl_id}?", 10, 10)
                            wrap_text(epd, "Press 'Select' to Confirm", 20, 30)
                            wrap_text(epd, "Press 'Down' to Try Again", 30, 50)
                            epd.update()
                            
                            waiting = True
                            while waiting:
                                if select_button.value() == 0:
                                    time.sleep(0.1)
                                    epd.clear(Color.WHITE)
                                    contacts[contact_name_str] = cl_id
                                    with open("contacts.json", "w") as f:
                                        json.dump(contacts, f)
                                    waiting = False
                                    creating_contact = False
                                elif down.value() == 0:
                                    epd.clear(Color.WHITE)
                                    waiting = False
                                machine.idle()
        
        elif u_select == 2: #Settings
            x_left  = 3
            x_right = 234
            y_mid   = 54

            epd.clear(Color.WHITE)
            epd.show_string("Press 'Record' to go back", 10, 10)
            epd.update()
            time.sleep(1)
            
            set_selection = 0
            last_selection = None

            while select_button.value() != 0 and record_button.value() != 0:
                if set_selection != last_selection:
                    epd.clear(Color.WHITE)
                    if set_selection == 0:
                        epd.show_bitmap(inverted_icons["inv_reset"], x_left, y_mid)
                        epd.show_bitmap(icons["Volume"], x_right, y_mid)
                    elif set_selection == 1:
                        epd.show_bitmap(icons["Reset"], x_left, y_mid)
                        epd.show_bitmap(inverted_icons["inv_vol"], x_right, y_mid)
                    epd.update()
                    last_selection = set_selection
                
                if up.value() == 0:
                    set_selection = 1 if set_selection == 0 else 0
                    time.sleep(0.2)
                elif down.value() == 0:
                    set_selection = 0 if set_selection == 1 else 1
                    time.sleep(0.2)
                machine.idle()

            if record_button.value() != 0:
                if set_selection == 0:
                    with open("contacts.json", "w") as f:
                        json.dump({}, f)
                    with open("history.json", "w") as f:
                        json.dump([], f)
                    with open("known_ids.json", "w") as f:
                        json.dump({}, f)
                        
                    epd.clear(Color.WHITE)
                    time.sleep(0.1)
                    epd.show_string("Your files have been cleared", 30, 30)
                    epd.update()
                    time.sleep(2)
                else:
                    # wait for the select press (that got us here) to release,
                    # otherwise the volume loop below reads it as an instant exit
                    while select_button.value() == 0:
                        time.sleep(0.02)
                    time.sleep(0.2)
                    last_vol = None
                    while select_button.value() != 0:
                        if percent_vol != last_vol:
                            epd.clear(Color.WHITE)
                            epd.show_string(f"Volume : {int(percent_vol * 100)}", 40, 40)
                            epd.update()
                            last_vol = percent_vol

                        if up.value() == 0 and percent_vol < 1.0:
                            percent_vol = min(1.0, percent_vol + 0.02)
                            time.sleep(0.05)
                        elif down.value() == 0 and percent_vol > 0.0:
                            percent_vol = max(0.0, percent_vol - 0.02)
                            time.sleep(0.05)
                        machine.idle()

        elif u_select == 3: #Group chat
            epd.clear(Color.WHITE)
            if gc_username is None or is_gc_username == False:
                wrap_text(epd, "Create a Username", 20, 20)
                percent = get_percent()
                draw_battery(epd, percent, epd.width - 40, 5)
                epd.update()
                time.sleep(1)
                
                creating_user = True
                while creating_user:
                    now_time = time.time()
                    epd.clear(Color.WHITE)
                    wrap_text(epd, "Record Your Username", 50, 50)
                    wrap_text(epd, "or press UP to type", 50, 70)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
                    
                    pre_txt = record_or_type(dev_ID, type_prompt="Type your username:")
                    gc_username = processing(pre_txt)
                    
                    epd.clear(Color.WHITE)
                    draw_battery(epd, percent, epd.width - 40, 5)
                    wrap_text(epd, f"Set Username to {gc_username}?", 10, 10)
                    wrap_text(epd, "Press 'Select' to Confirm", 20, 30)
                    wrap_text(epd, "Press 'Down' to Try Again", 30, 50)
                    epd.update()
                    
                    waiting = True
                    while waiting:
                        if select_button.value() == 0:
                            time.sleep(0.1)
                            epd.clear(Color.WHITE)
                            with open("gc_username.json", "w") as f:
                                json.dump(gc_username, f)
                            is_gc_username = True
                            creating_user = False
                            waiting = False
                        elif down.value() == 0:
                            epd.clear(Color.WHITE)
                            waiting = False
                        machine.idle()
                    
            full_req = f"gc{gc_username}"
            my_id = dev_ID
            
            user_gc_choice = gc_UI(is_past_msg_sent)

            if user_gc_choice == 1 or (user_gc_choice == 0 and not is_past_msg_sent):
                sending_gc = True
                while sending_gc:
                    now_time = time.time()
                    epd.clear(Color.WHITE)
                    wrap_text(epd, "Record Your Message", 50, 50)
                    wrap_text(epd, "or press UP to type", 50, 70)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
                    
                    snd_txt = record_or_type(dev_ID, type_prompt="Type your message:")
                    msg = processing(snd_txt)
                        
                    epd.clear(Color.WHITE)
                    draw_battery(epd, percent, epd.width - 40, 5)
                    wrap_text(epd, f"Send: {msg}?", 10, 10)
                    wrap_text(epd, "Press 'Select' to Confirm", 20, 30)
                    wrap_text(epd, "Press 'Down' to Try Again", 30, 50)
                    epd.update()
                    
                    waiting = True
                    while waiting:
                        if select_button.value() == 0:
                            time.sleep(0.1)
                            epd.clear(Color.WHITE)
                            r = urequests.post(f"{BASE_URL}/gc?Request={full_req}&ID={dev_ID}&Message={msg}")
                            sent_comf = r.json()
                            is_past_msg_sent = True
                            sending_gc = False
                            waiting = False
                        elif down.value() == 0:
                            epd.clear(Color.WHITE)
                            waiting = False
                        machine.idle()

            elif user_gc_choice == 0 and is_past_msg_sent == True:
                epd.clear(Color.WHITE)
                gc_letters = req_update("serv_letters")
                hist = req_update("prov_hist")
                
                if hist:
                    for msg_obj in hist:
                        msg_obj["Message"] = ce.decipher(msg_obj["Message"], gc_letters)
                    
                    msg_num = 0
                    past_msg_num = None
                    epd.show_string("Press 'Record' to go back", 20, 20)
                    epd.update()
                    time.sleep(1)

                    while record_button.value() != 0:
                        if past_msg_num != msg_num:
                            epd.clear(Color.WHITE)
                            wrap_text(epd, f"{hist[msg_num]['Username']}: {hist[msg_num]['Message']}", 20, 10)
                            epd.update()
                            past_msg_num = msg_num

                        if up.value() == 0:
                            msg_num = 0 if msg_num >= len(hist) - 1 else msg_num + 1
                            time.sleep(0.2)
                        elif down.value() == 0:
                            msg_num = len(hist) - 1 if msg_num <= 0 else msg_num - 1
                            time.sleep(0.2)
                        machine.idle()
                else:
                    epd.clear(Color.WHITE)
                    wrap_text(epd, "No Group Chat history yet", 20, 20)
                    epd.update()
                    time.sleep(2)
                
        elif u_select == 5: #Wait for any messages
            device = esp_network_client()
            device.client(use_message, percent_vol=percent_vol)
            machine.idle()


    except Exception as e:
        epd.clear(Color.WHITE)
        wrap_text(epd, f"Error {e}", 10, 30)
        percent = get_percent()
        draw_battery(epd, percent, epd.width - 40, 5)
        epd.update()
        time.sleep(3)
        pass
