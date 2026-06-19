import Cencrypt as ce
import network
import time
import utime
import json
import ujson
import os
import random
import urequests
import machine
import math
import binascii
from ssd1680 import SSD1680, Color
from machine import Pin, ADC, SPI, PWM, I2C, DAC

#_____________________________________Button Setup_______________________________________

"""
There are 6 different push buttons
 - Record
 - Send Message
 - Select
 - Up
 - Down
 -Shut-off
"""

record_button = Pin(5, Pin.IN, Pin.PULL_UP) 
send_mes_button = Pin(15, Pin.IN, Pin.PULL_UP)
select_button = Pin(39, Pin.IN, Pin.PULL_UP)
up = Pin(8, Pin.IN, Pin.PULL_UP)
down = Pin(38, Pin.IN, Pin.PULL_UP)
shut_off = Pin(16, Pin.IN, Pin.PULL_UP)

#____________________________________Voltage Sensing_____________________________________

#Uses the onboard voltage/battery percentage reader
MAX17048_ADDR = 0x36

i2c = I2C(0, scl=Pin(4), sda=Pin(3))  

def read_register(reg):
    data = i2c.readfrom_mem(MAX17048_ADDR, reg, 2)
    return (data[0] << 8) | data[1]

def get_percent():
    raw = read_register(0x04)
    return raw / 256

def draw_battery(epd, percent, x, y): 
    """
    Draws a battery icon on the top-right corner of the e-ink display.
    It uses the percentage found in the previous functions.
    """
    percent = max(0, min(100, percent))
    
    #Set dimensions of the battery monitor
    width = 30
    height = 12
    nub_width = 3

    epd.draw_rectangle(x, y, x + width, y + height)

    epd.draw_rectangle(x + width, y + 3, x + width + nub_width, y + height - 3)

    fill_width = int((width - 4) * (percent / 100))

    for fy in range(y + 2, y + height - 1):
        epd.draw_line(x + 2, fy, x + 2 + fill_width, fy)

#______________________________________Piezo Setup_______________________________________

dac = DAC(Pin(17)) #Uses the DAC pin (A0) on the microcontroller for speaker output

def play_tone(frequency, percent_vol=1, duration=0.3, sample_rate=8000): 
    """
    This is the backbone function of all of the chimes
    This determines the DAC output based on the frequency
    """

    num_samples = int(sample_rate * duration)
    amplitude = 127 * max(0, min(1, percent_vol))  #Clamps volume to 0-1, scale to half of 8-bit range

    delay_us = int(1_000_000 / sample_rate)

    for i in range(num_samples):
        angle = 2 * math.pi * frequency * i / sample_rate
        sample = int(128 + amplitude * math.sin(angle))  #Center at 128, swing amplitude
        dac.write(sample)
        time.sleep_us(delay_us)


def notif_chime(percent_vol=1):
    play_tone(3000, percent_vol, 0.3)
    play_tone(2000, percent_vol, 0.3)
    play_tone(1000, percent_vol, 0.3)
    play_tone(3000, percent_vol, 0.3)
    dac.write(128)  #Return to silence (midpoint = no signal). Equivalent to .deinit() for the previous choice of piezo


def handcryption_chime(percent_vol=1): #Chime on boot
    tones = [
        (1800, 0.18),
        (1400, 0.15),
        (900, 0.12),
        (1600, 0.15),
        (2200, 0.20),
        (2600, 0.10)
    ]
    for freq, duration in tones:
        play_tone(freq, percent_vol, duration)
    dac.write(128)


def wake_chime(percent_vol=1):
    play_tone(1500, percent_vol, 0.15)
    play_tone(3000, percent_vol, 0.3)
    dac.write(128)


def shut_off_chime(percent_vol=1):
    play_tone(3000, percent_vol, 0.15)
    play_tone(2000, percent_vol, 0.15)
    play_tone(1000, percent_vol, 0.15)
    dac.write(128)
#______________________________________E-ink Setup_______________________________________

"""
This e-ink display is a Adafruit 2.13" 
Monochrome eInk / ePaper Display with SRAM 
250x122 Monochrome with SSD1680

The SSD1680 driver used is in the README
"""

#Setting up pins
spi = SPI(
    2,
    baudrate=4000000,
    polarity=0,
    phase=0,
    sck=Pin(36),
    mosi=Pin(35),
    miso=Pin(37)   #Not used by display
)

dc   = Pin(12, Pin.OUT)
busy = Pin(6, Pin.IN)
cs   = Pin(13, Pin.OUT)
res  = Pin(9, Pin.OUT)

#Initializing epd
epd = SSD1680(spi, dc, busy, cs, res)

epd.init()

epd.clear(Color.WHITE)

#_____________________________________Voice to Text______________________________________

adc = ADC(Pin(17)) #Analog input for microphone

SAMPLE_RATE = 8000 #8 kHz audio
FILENAME = "recording.wav" 

def write_wav_header(file, num_samples):
    file.write(b"RIFF")
    file.write((36 + num_samples).to_bytes(4, "little"))
    file.write(b"WAVEfmt ")
    file.write((16).to_bytes(4, "little"))
    file.write((1).to_bytes(2, "little"))      #PCM
    file.write((1).to_bytes(2, "little"))      #mono
    file.write(SAMPLE_RATE.to_bytes(4, "little"))
    file.write((SAMPLE_RATE * 2).to_bytes(4, "little"))
    file.write((2).to_bytes(2, "little"))      #block align
    file.write((16).to_bytes(2, "little"))     #bits per sample
    file.write(b"data")
    file.write(num_samples.to_bytes(4, "little"))

def collect_audio(samples):
    raw = adc.read_u16() >> 4          #12‑bit sample
    samples.append(raw.to_bytes(2, "little"))
    utime.sleep_us(125)   

    return samples

def request_n_parse_translation(dev_id):
    url = "https://blog-skipping-send.ngrok-free.dev/stt" #Requests for .wav to be translated to text through the Raspberry Pi server
    with open("recording.wav", "rb") as f:
        r = urequests.post(url, files={"file": f}, data={"Request" : "transl", "ID" : dev_id}) #Request
    
    data = ujson.loads(r.text)
    text = data["text"]

    return text

def encrypt_audio(pub_key, data: bytes) -> str:
    """
    This function encrypts audio for voice texting

    It uses RSA encryption to encrypt the key used to shift the bytes
    """

    key = os.urandom(32)
    key_as_int = int.from_bytes(key, "big") #Gets the key as an integer to perform operations on it
    encrypted_key = encrypt_audio_key(pub_key, key_as_int)
    cipher = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    combined = encrypted_key + cipher
    return binascii.b2a_base64(combined).decode("utf-8").strip() #Returns encrypted audio in binary form

def decrypt_audio(priv_key, encoded: str) -> bytes:
    """
    As the name suggests, this function reverses the RSA
    encryption of the key to decrypt the audio
    """

    d, n = priv_key #Extracts variables d and n from the priv_key tuple
    key_size = (n.bit_length() + 7) // 8 #The shift depends on the bit size of the key

    combined = binascii.a2b_base64(encoded)
    encrypted_key_bytes = combined[:key_size]
    cipher = combined[key_size:]

    encrypted_key_int = int.from_bytes(encrypted_key_bytes, "big")
    key_int = pow(encrypted_key_int, d, n)
    key = key_int.to_bytes(32, "big")

    return bytes(b ^ key[i % len(key)] for i, b in enumerate(cipher)) #Returns the decrypted audio

def play_pcm(pcm_data: bytes, sample_rate=8000, percent_vol=1):
    """
    This function plays the .wav voice messages
    based on the pcm data extracted from the .wav
    """
    delay_us = int(1_000_000 / sample_rate)
    percent_vol = max(0, min(1, percent_vol))
    
    for i in range(0, len(pcm_data) - 1, 2):
        raw_sample = int.from_bytes(pcm_data[i:i+2], "little")
        sample_8 = raw_sample >> 4 #Converts to 8-bit. This is what the DAC used
        
        deviation = sample_8 - 128
        scaled_deviation = int(deviation * percent_vol)
        final_sample = 128 + scaled_deviation
        
        dac.write(final_sample) #Writes the scaled pcm data to the DAC output
        time.sleep_us(delay_us)

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

def record_and_confirm_text(prompt_label):
    """
    This is the function that records either the wifi
    name or the wifi password.

    It asks the user to record their response and allows
    them to edit it using the confirm_wifi_password function
    """
    while True:
        now_time = time.time()
        epd.show_string(f"Record the {prompt_label}", 50, 50)
        percent = get_percent()
        draw_battery(epd, percent, epd.width - 40, 5)
        epd.update()

        #Record
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
        
    ssid = record_and_confirm_text("WiFi Name")
    epd.clear(Color.WHITE)
    password = record_and_confirm_text("Password")
    knownwifis.append((ssid, password))
    with open("wifi.json", "w") as f:
        json.dump(knownwifis, f)

def connect_to_my_wifi(ssid, password, timeout=20):
    """
    As the name suggests, this function connects to 
    a wifi network using the ssid and pasword arguments
    """

    wlan = network.WLAN(network.WLAN.IF_STA)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(ssid, password)
        start = time.time()
        while not wlan.isconnected():
            if time.time() - start > timeout:
                return "Wi-Fi connection timed out"
            time.sleep(0.5)
    return wlan

if not os.path.exists("wifi.json"):
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

#Create other json files for device info storage
if not os.path.exists("known_ids.json"):
    with open("known_ids.json", "w") as f:
        f.close()

if not os.path.exists("my_letters.json"):
    with open("my_letters.json", "w") as f:
        f.close()

if not os.path.exists("contacts.json"):
    with open("contacts.json", "w") as f:
        f.close()

if not os.path.exists("history.json"):
    with open("history.json", "w") as f:
        f.close()

if not os.path.exists("device_ID.json"):
    with open("device_ID.json", "w") as f:
        dev_ID = random.randrange(100000000, 999999999) #This is the unique device ID used when communicating with the server
        id_clear = urequests.post(f"https://blog-skipping-send.ngrok-free.dev/getID?req_ID={dev_ID}") #Confirms if ID is unique
        recv = id_clear.json()
        if recv == "Clear":
            f.write(str(dev_ID))
        else: #If the ID generated wasn't unique
            dev_ID = recv #Sets the device ID to what the server created
            f.write(recv)
else:
    with open("device_ID.json", "r") as f:
        dev_ID = f.read().strip()

if not os.path.exists("gc_username.json"):
    with open("gc_username.json", "w") as f:
        f.close()
    is_gc_username = False
else:
    is_gc_username = True
    with open("gc_username.json", "r") as f:
        gc_username = json.load(f)
        f.close()

#_____________________________________RSA Encryption________________________________________
"""
This is the information needed for the RSA encryption
"""
E = 65537
if not os.path.exists("priv_keys.json"):
    get_prime_json = urequests.post("https://blog-skipping-send.ngrok-free.dev/get_prime")
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
    urequests.post("https://blog-skipping-send.ngrok-free.dev/updates", data=payload, headers={"Content-Type": "application/json"})

    with open("priv_keys.json", "w") as f:
        json.dump(package, f)
        
else:
    with open("priv_keys.json", "r") as f:
        data = json.load(f)
        data_joined = "".join(data)
        re_split_data = data_joined.split("/")

        phi = int(re_split_data[0])
        d = int(re_split_data[1])
        n = int(re_split_data[2])
        key1 = int(re_split_data[3])
        key2 = int(re_split_data[4])

        my_pub_key = (E, n)
        my_priv_key = (d, n)

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
        if os.path.exists(self.contacts_path):
            with open(self.contacts_path, "r") as f:
                self.contacts = json.load(f)
        else:
            self.contacts = {}

        self.message_to_send = ""

    def load_known_ids(self): #Unknown ids get new letters, so, the device logs the ones it knows
        #Load known ids properly
        if os.path.exists(self.known_ids_path):
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
            
            #Each known ID gets its own Letters for ciphering
            self.clients[self.target_id] = {
                "letters": LETTERS
            }

            if self.target_id not in self.known_ids: #New device logic

                wrap_text(epd, f"New device: {self.target_id}. Enter a contact name: ", 20, 20)
                percent = get_percent()
                draw_battery(epd, percent, epd.width - 40, 5)
                epd.update()
                time.sleep(0.1)
                while True:
                    now_time = time.time()
                    wrap_text(epd, "Record the Contact", 50, 50)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
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
                    processed_txt = processing(txt)
                    epd.clear(Color.WHITE)
                    time.sleep(0.1)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    wrap_text(epd, f"Set contact to {processed_txt}?", 10, 10)
                    epd.update()
                    time.sleep(0.1)
                    wrap_text(epd, "Press 'Select' to Confirm", 20, 20)
                    wrap_text(epd, "Press 'Down' to Try Again", 30, 30)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
                    if up.value() == 0:
                        time.sleep(0.1)
                        epd.clear(Color.WHITE)
                        break
                    elif down.value() == 0:
                        epd.clear(Color.WHITE)
                        continue

                name_ = processed_txt
                self.contacts[name_] = self.target_id

                with open(self.contacts_path, "w") as f:
                    json.dump(self.contacts, f)

                #First time this id connects, give their key
                random.shuffle(LETTERS)
                self.known_ids[self.target_id] = LETTERS.copy()

                # Send alphabet
                alph = json.dumps(self.known_ids[self.target_id])
                payload = ujson.dumps({"msg": alph, "destinationID": self.target_id, "senderID": dev_ID, "type": "key_exchange"})
                send = urequests.post(f"https://blog-skipping-send.ngrok-free.dev/send-msg",
                               data=payload,
                               headers={"Content-Type": "application/json"})

                # Save updated known_ids
                with open(self.known_ids_path, "w") as f:
                    json.dump(self.known_ids, f)

            client_letters = self.known_ids[self.target_id]

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
                if os.path.exists("history.json"):
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
                urequests.post(f"https://blog-skipping-send.ngrok-free.dev/send-msg", #Send message to server
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
            if os.path.exists("my_letters.json"):
                with open("my_letters.json", "r") as f:
                    data = f.read().strip()
                    if data:
                        LETTERS = json.loads(data)
                    else:
                        LETTERS = None
                
            if os.path.exists("device_ID.json"):
                with open("device_ID.json", "r") as f:
                    data = f.read().strip()
                    my_id = json.loads(data)
            
            while self.running:
                msgs = req_update("check_mail", my_id)

                with open("contacts.json", "r") as f:
                     my_contacts = json.load(f)
                
                for item in msgs:
                    dest = item["destinationID"]
                    d_msg = item["msg"]
                    sender_ID = item["senderID"]
                    msg_type = item["type"] #Extract message type from server return

                    for key, value in my_contacts.items():
                        if value == sender_ID:
                            cont_name = key
                            break

                    else:
                        cont_name = sender_ID
                    
                    #Handle different message types
                    if msg_type == "txt":
                        true_message = ce.decipher(d_msg, alphabet=LETTERS)
                        notif_chime(percent_vol=percent_vol)
                        out_message(true_message, cont_name)
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

    #Scale to target width/height
    scale_x = max(1, width // len(rows[0]))
    scale_y = max(1, height // len(rows))

    bitmap = []
    for row in rows:
        scaled_row = []
        for pixel in row:
            scaled_row += [pixel] * scale_x
        for _ in range(scale_y):
            bitmap.append(scaled_row[:width])  #trim to exact width

    return bitmap[:height]  #trim to exact height

icons = {   #icons generated by AI
    "settings" : [
 [0,0,1,0,1,1,1,0,1,0,0],
 [0,1,0,1,1,0,1,1,0,1,0],
 [1,0,1,1,1,1,1,1,1,0,1],
 [0,1,1,1,1,1,1,1,1,1,0],
 [1,0,1,1,1,1,1,1,1,0,1],
 [1,0,1,1,1,0,1,1,1,0,1],
 [1,0,1,1,1,1,1,1,1,0,1],
 [0,1,1,1,1,1,1,1,1,1,0],
 [1,0,1,1,1,1,1,1,1,0,1],
 [0,1,0,1,1,0,1,1,0,1,0],
 [0,0,1,0,1,1,1,0,1,0,0]
], "history" : [
 [0,1,1,1,1,1,1,1,1,1,1,1,0],
 [1,0,0,0,0,0,0,0,0,0,0,0,1],
 [1,0,1,1,1,1,1,1,1,1,1,0,1],
 [1,0,0,1,1,1,1,1,1,1,0,0,1],
 [1,0,0,0,1,1,1,1,1,0,0,0,1],
 [1,0,0,0,0,1,1,1,0,0,0,0,1],
 [1,0,0,0,0,0,1,0,0,0,0,0,1],
 [1,0,0,0,0,0,0,0,0,0,0,0,1],
 [0,1,1,1,1,1,1,1,1,1,1,1,0]
], "Contacts" : [
 [0,0,0,1,1,1,0,0,0],
 [0,0,1,1,1,1,1,0,0],
 [0,0,1,1,1,1,1,0,0],
 [0,0,0,1,1,1,0,0,0],
 [0,0,0,0,0,0,0,0,0],
 [0,0,1,1,1,1,1,0,0],
 [0,1,1,1,1,1,1,1,0],
 [1,1,1,1,1,1,1,1,1],
 [1,1,1,1,1,1,1,1,1]
], "Up" : [
 [0,0,1,0,0],
 [0,1,1,1,0],
 [1,0,1,0,1],
 [0,0,1,0,0],
 [0,0,1,0,0]
], "Down" : [
 [0,0,1,0,0],
 [0,0,1,0,0],
 [1,0,1,0,1],
 [0,1,1,1,0],
 [0,0,1,0,0]
], "Volume" : [
 [0,0,0,0,1,0,0,0,0,0,0,0,0],
 [0,0,0,1,1,1,0,0,0,0,0,0,0],
 [0,0,1,1,1,1,0,0,1,0,0,0,0],
 [0,1,1,1,1,1,0,0,0,1,0,0,0],
 [1,1,1,1,1,1,0,1,0,0,1,0,0],
 [1,1,1,1,1,1,0,0,1,0,0,1,0],
 [1,1,1,1,1,1,0,0,1,0,0,1,0],
 [1,1,1,1,1,1,0,1,0,0,1,0,0],
 [0,1,1,1,1,1,0,0,0,1,0,0,0],
 [0,0,1,1,1,1,0,0,1,0,0,0,0],
 [0,0,0,1,1,1,0,0,0,0,0,0,0],
 [0,0,0,0,1,0,0,0,0,0,0,0,0],
 [0,0,0,0,0,0,0,0,0,0,0,0,0]
], "Reset" : [
 [1,0,0,0,0,0,0,0,0,0,0,0,1],
 [0,1,0,0,0,0,0,0,0,0,0,1,0],
 [0,0,1,0,0,0,0,0,0,0,1,0,0],
 [0,0,0,1,0,0,0,0,0,1,0,0,0],
 [0,0,0,0,1,0,0,0,1,0,0,0,0],
 [0,0,0,0,0,1,0,1,0,0,0,0,0],
 [0,0,0,0,0,0,1,0,0,0,0,0,0],
 [0,0,0,0,0,1,0,1,0,0,0,0,0],
 [0,0,0,0,1,0,0,0,1,0,0,0,0],
 [0,0,0,1,0,0,0,0,0,1,0,0,0],
 [0,0,1,0,0,0,0,0,0,0,1,0,0],
 [0,1,0,0,0,0,0,0,0,0,0,1,0],
 [1,0,0,0,0,0,0,0,0,0,0,0,1]
], "gc_icon" : [
 [0,0,1,1,1,1,1,1,1,0,0],
 [0,1,0,0,0,0,0,0,0,1,0],
 [1,0,0,0,0,0,0,0,0,0,1],
 [1,0,0,0,0,0,0,0,0,0,1],
 [1,0,0,0,0,0,0,0,0,0,1],
 [1,1,1,1,1,1,1,1,1,1,1],
 [0,0,0,0,0,1,1,1,0,0,0],
 [0,0,0,0,0,0,1,1,0,0,0],
 [0,0,0,0,0,0,1,1,0,0,0],
 [0,0,0,0,0,0,0,1,0,0,0],
 [0,0,0,0,0,0,0,1,0,0,0]
], "send_icon" : [
 [0,1,1,1,1,1,0,0,0,0,0,0,0],
 [0,1,1,1,1,1,1,0,0,0,0,0,0],
 [0,1,1,1,1,1,1,1,0,0,0,0,0],
 [0,1,1,1,1,1,1,1,1,0,0,0,0],
 [0,1,1,1,1,1,1,1,1,1,0,0,0],
 [0,0,1,1,1,1,1,1,1,1,1,0,0],
 [0,0,0,0,0,1,1,1,1,1,1,1,0],
 [0,0,1,1,1,1,1,1,1,1,1,0,0],
 [0,1,1,1,1,1,1,1,1,1,0,0,0],
 [0,1,1,1,1,1,1,1,1,0,0,0,0],
 [0,1,1,1,1,1,1,1,0,0,0,0,0],
 [0,1,1,1,1,1,1,0,0,0,0,0,0],
 [0,1,1,1,1,1,0,0,0,0,0,0,0]
]




}

def invert(bitmap):
    """
    This inverts bitmaps, mainly the icons create
    in the above dictionary
    """
    for row in bitmap:
        for px in range(0, len(row)):
            row[px] = 1 - row[px]
    
    return bitmap
    
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
    This is the UI seen when the user 
    wakes the device.

    The user can choose features from the main menu
    """

    epd.clear(Color.WHITE)
    epd.show_bitmap(icons["settings"], 239, 111)
    epd.show_bitmap(icons["Contacts"], 120, 110)
    epd.show_bitmap(icons["history"], 3, 110)
    epd.show_bitmap(icons["gc_icon"], 119, 5)
    epd.update()
    selection = 0
    idle_time = time.time()
    while select_button.value() != 0 and send_mes_button.value() != 0:
        percent = get_percent()
        draw_battery(epd, percent, epd.width - 40, 5)
        epd.update()

        #Add flashing icons
        if selection == 2:
            epd.show_bitmap(inverted_icons["inv_settings"], 239, 111)
            epd.update()
            time.sleep(0.2)
            epd.show_bitmap(icons["settings"], 239, 111)
            epd.update()
        elif selection == 1:
            epd.show_bitmap(inverted_icons["inv_contacts"], 120, 110)
            epd.update()
            time.sleep(0.2)
            epd.show_bitmap(icons["Contacts"], 120, 110)
            epd.update()
        elif selection == 0:
            epd.show_bitmap(inverted_icons["inv_hist"], 3, 110)
            epd.update()
            time.sleep(0.2)
            epd.show_bitmap(icons["history"], 3, 110)
            epd.update()
        elif selection == 3:
            epd.show_bitmap(inverted_icons["inv_gc"], 119, 5)
            epd.update()
            time.sleep(0.2)
            epd.show_bitmap(icons["gc_icon"], 119, 5)
            epd.update()

        if up.value() == 0 and selection < 3:
            selection = selection + 1
            time.sleep(0.4)
        elif down.value() == 0 and selection > 0:
            selection = selection - 1
            time.sleep(0.4)
        #Exceptions
        elif up.value() == 0 and selection >= 3:
            selection = 0
            time.sleep(0.4)
        elif down.value() == 0 and selection <= 0:
            selection = 2
            time.sleep(0.4)
        elif send_mes_button.value() == 0:
            selection = 4
            time.sleep(0.2)
        
        if time.time() - idle_time >= 60:
            return 5
            

    if send_mes_button.value() == 0:
        selection = 4
        time.sleep(0.1)
    
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
        
def req_update(request, device_id=None):
    """
    This allows the device to request updates from the server.
    Using this, the device can check for new messages
    """
    r = urequests.get(f"https://blog-skipping-send.ngrok-free.dev/updates?Request={request}&dev_id={device_id}")
    data = r.json()

    return data

#Opening Screen
handcryption_bitmap = render_block_text("HANDCRYPTION", 220, 30)
recording_bitmap = render_block_text("RECORDING", 220, 30)
tap_bitmap = render_block_text("Press a Button to Continue", 220, 30)
x_start = (epd.width - 220) // 2
y_start = (epd.height - 30) // 2

percent_vol = 1 #Volume is originally 100%
epd.show_bitmap(handcryption_bitmap, x_start, y_start)
epd.update()
percent = get_percent()
draw_battery(epd, percent, epd.width - 40, 5)
handcryption_chime(percent_vol=percent_vol)

gc_username = None
is_past_msg_sent = False

time.sleep(2)

#Main loop
while True:
    try:
        epd.show_bitmap(tap_bitmap, x_start, y_start)
        epd.update()
        while select_button.value() == 1 and down.value() == 1 and up.value() == 1 and send_mes_button.value() == 1 and record_button.value() == 1:
            machine.idle() #Idle when there is no interaction

        wake_chime(percent_vol=percent_vol)
        epd.clear(Color.WHITE)
        time.sleep(0.2)
        percent = get_percent()
        draw_battery(epd, percent, epd.width - 40, 5)
        epd.update()
        time.sleep(0.3)
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
            while select_button.value() != 0:
                epd.clear(Color.WHITE)
                epd.show_string("Who do you want to send this to?", 20, 10)
                wrap_text(epd, "If you don't have any contacts, go to contacts to create on. Press record to do so", 30, 10)
                epd.update()
                time.sleep(0.1)
                if record_button.value() == 0:
                    time.sleep(0.07)
                    cont_num = None
                    break
                epd.show_string(contact_list[cont_num], 20, 25)
                percent = get_percent()
                draw_battery(epd, percent, epd.width - 40, 5)
                epd.update()
                if down.value() == 0 and cont_num != (len(contact_list) - 1):
                    cont_num = cont_num + 1
                    time.sleep(0.2)
                elif cont_num != 0 and up.value() == 0:
                    cont_num = cont_num - 1
                    time.sleep(0.2)
                elif cont_num == 0 and up.value() == 0:
                    cont_num = (len(contact_list) - 1)
                    time.sleep(0.2)
                elif cont_num == (len(contact_list) - 1) and down.value() == 0:
                    cont_num = 0
                    time.sleep(0.2)
                else:
                    continue

            wrap_text(epd, "Do you want to send in text (up) or voice (down)?", 20, 20)
            epd.update()
            sel = None
            while sel == None:
                if up.value() == 0:
                    sel = 0
                    break
                elif down.value() == 0:
                    sel = 1
                    break
                time.sleep(0.1)
            if sel == 0:
                now_time = time.time()
                rec = True
                while time.time() - now_time < 60 and rec == True:
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
                    
                    epd.clear(Color.WHITE)
                    txt = request_n_parse_translation(dev_ID)
                    processed_txt = processing(txt)
                    wrap_text(epd, f"Message: {processed_txt}", 10, 10)
                    wrap_text(epd, "Press 'UP' to Confirm the message, 'DOWN' to Try Again", 10, 50)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
                    if up.value() == 0:
                        time.sleep(0.1)
                        epd.clear(Color.WHITE)
                        break
                    elif down.value() == 0:
                        epd.clear(Color.WHITE)
                        continue
            else:
                now_time = time.time()
                rec = True
                while time.time() - now_time < 60 and rec == True:
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
                            f.close()
                
                with open(FILENAME, "rb") as f:
                    audio_bytes = f.read()

                pcm_data = audio_bytes[44:]
    
            if cont_num == None:
                u_select = 1
                continue
            elif sel == 0:
                target_name = contact_list[cont_num]
                target_id = contacts[target_name]
                device = esp_network_server()
                device.run(get_processed_message, target_id, target_name)
            elif sel == 1:
                target_name = contact_list[cont_num]
                target_id = contacts[target_name]
                payload = ujson.dumps({"Request": "get_cont_pub_key", "targ_id": target_id})
                cli_pub_key_data = urequests.post(f"https://blog-skipping-send.ngrok-free.dev/updates",
                               data=payload,
                               headers={"Content-Type": "application/json"})
                cli_pub_key_data = cli_pub_key_data.json()
                cli_pub_key = (cli_pub_key_data["e"], cli_pub_key_data["n"])
                encrypted_audio_to_send = encrypt_audio(cli_pub_key, pcm_data)
                payload = ujson.dumps({"msg": encrypted_audio_to_send, "type": "audio", "destinationID" : target_id, "senderID" : dev_ID})
                send = urequests.post(f"https://blog-skipping-send.ngrok-free.dev/send-msg",
                               data=payload,
                               headers={"Content-Type": "application/json"})
                
        elif u_select == 0: #Message history
            DEL_CHARS = ["{", "}", "[", "]"]
            if os.path.exists("history.json"):
                with open("history.json", "r") as f:
                    try:
                        epd.show_string("Press 'Record' to go back", 20, 20)
                        epd.update(1.3)
                        history = json.load(f)
                        epd.clear(Color.WHITE)
                        epd.draw_rectangle(7, 7, 243, 115)
                        hist_num = 0
    
                        while record_button.value() != 0:
                            wrap_text(epd, json.dumps(history[hist_num]), 16, 12)
                            if hist_num > 0 and hist_num < len(history) - 1:
                                epd.show_bitmap(icons["Up"], 9, 9)
                                epd.show_bitmap(icons["Down"], 256, 108)
                            elif hist_num == 0:
                                epd.show_bitmap(icons["Down"], 256, 108)
                            else:
                                epd.show_bitmap(icons["Up"], 9, 9)

                            epd.update()
                            if up.value() == 0 and hist_num < (len(history) - 1):
                                hist_num = hist_num + 1
                                time.sleep(0.2)
                            elif down.value() == 0 and hist_num > 0:
                                hist_num = hist_num - 1
                                time.sleep(0.2)
                            elif up.value() == 0 and hist_num >= (len(history) - 1):
                                hist_num = 0
                                time.sleep(0.2)
                            elif down.value() == 0 and hist_num == 0:
                                hist_num = len(history) - 1

                    except:
                        wrap_text(epd, "Sorry, you have no current history. Send a message to start saving history", 20, 20)
                        epd.update()
            else:
                wrap_text(epd, "Sorry, you have no current history. Send a message to start saving history", 20, 20)
                epd.update()

        elif u_select == 1: #Contacts
            epd.clear(Color.WHITE)
            DEL_CHARS = ["{", "}", "[", "]"]
            if os.path.exists("contacts.json") and os.path.getsize("contacts.json") > 0:
                with open("contacts.json", "r") as f:
                    try:
                        epd.show_string("Press 'Record' to go back", 20, 20)
                        epd.update(1.3)
                        stored_contacts = json.load(f)
                        epd.clear(Color.WHITE)
                        epd.draw_rectangle(7, 7, 243, 115)
                        cont_num = 0
    
                        while record_button.value() != 0:
                            wrap_text(epd, processing(f"{stored_contacts[cont_num]}", del_words=DEL_CHARS), 16, 12)
                            if cont_num > 0 and cont_num < len(stored_contacts) - 1:
                                epd.show_bitmap(icons["Up"], 9, 9)
                                epd.show_bitmap(icons["Down"], 256, 108)
                            elif cont_num == 0:
                                epd.show_bitmap(icons["Down"], 256, 108)
                            else:
                                epd.show_bitmap(icons["Up"], 9, 9)

                            epd.update()
                            if up.value() == 0 and cont_num < (len(stored_contacts) - 1):
                                cont_num = cont_num + 1
                                time.sleep(0.2)
                            elif down.value() == 0 and cont_num > 0:
                                cont_num = cont_num - 1
                                time.sleep(0.2)
                            elif up.value() == 0 and cont_num >= (len(stored_contacts) - 1):
                                cont_num = 0
                                time.sleep(0.2)
                            elif down.value() == 0 and cont_num == 0:
                                cont_num = len(stored_contacts) - 1

                    except Exception:
                        contacts = {}
                        wrap_text(epd, "Create a contact", 20, 20)
                        percent = get_percent()
                        draw_battery(epd, percent, epd.width - 40, 5)
                        epd.update()
                        time.sleep(0.1)
                        while True:
                            now_time = time.time()
                            wrap_text(epd, "Record the Contact Name", 50, 50)
                            percent = get_percent()
                            draw_battery(epd, percent, epd.width - 40, 5)
                            epd.update()
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
                            processed_txt = processing(txt)

                            epd.clear(Color.WHITE)
                            now_time = time.time()
                            wrap_text(epd, "Record the ID", 50, 50)
                            percent = get_percent()
                            draw_battery(epd, percent, epd.width - 40, 5)
                            epd.update()
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
                            epd.update()
                            time.sleep(0.1)
                            wrap_text(epd, "Press 'Select' to Confirm", 20, 20)
                            wrap_text(epd, "Press 'Down' to Try Again", 30, 30)
                            percent = get_percent()
                            draw_battery(epd, percent, epd.width - 40, 5)
                            epd.update()
                            if select_button.value() == 0:
                                time.sleep(0.1)
                                epd.clear(Color.WHITE)
                                break
                            elif down.value() == 0:
                                epd.clear(Color.WHITE)
                                continue

                        name_ = processed_txt
                        contacts[name_] = cl_id

                        with open("contacts.json", "w") as f:
                            json.dump(contacts, f)

            else:
                contacts = {}
                wrap_text(epd, "Sorry, you have no current contacts. Please create one", 20, 20)
                percent = get_percent()
                draw_battery(epd, percent, epd.width - 40, 5)
                epd.update()
                time.sleep(0.1)
                while True:
                    now_time = time.time()
                    wrap_text(epd, "Record the Contact", 50, 50)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
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
                    processed_txt = processing(txt)

                    epd.clear(Color.WHITE)
                    now_time = time.time()
                    wrap_text(epd, "Record the ID", 50, 50)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
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
                    epd.update()
                    time.sleep(0.1)
                    wrap_text(epd, "Press 'Select' to Confirm", 20, 20)
                    wrap_text(epd, "Press 'Down' to Try Again", 30, 30)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
                    if up.value() == 0:
                        time.sleep(0.1)
                        epd.clear(Color.WHITE)
                        break
                    elif down.value() == 0:
                        epd.clear(Color.WHITE)
                        continue

                name_ = processed_txt
                contacts[name_] = cl_id

                with open("contacts.json", "w") as f:
                    json.dump(contacts, f)
        
        elif u_select == 2: #Settings
            x_left  = 3
            x_right = 234
            y_mid   = 54

            epd.clear(Color.WHITE)
            epd.show_string("Press 'Record' to go back")
            epd.update()
            time.sleep(1)
            epd.clear(Color.WHITE)
            epd.show_bitmap(icons["Reset"], x_left, y_mid) #Factory Reset
            epd.show_bitmap(icons["Volume"], x_right, y_mid)
            epd.update()
            set_selection = 0

            while select_button.value() != 0 and record_button.value() != 0:
                if set_selection == 0:
                    epd.show_bitmap(inverted_icons["inv_reset"], x_left, y_mid)
                    epd.update()
                    time.sleep(0.2)
                    epd.show_bitmap(icons["Reset"], x_left, y_mid)
                    epd.update()
                elif set_selection == 1:
                    epd.show_bitmap(inverted_icons["inv_vol"], x_right, y_mid)
                    epd.update()
                    time.sleep(0.2)
                    epd.show_bitmap(icons["Volume"], x_right, y_mid)
                    epd.update()
                
                if up.value() == 0 and set_selection == 0:
                    set_selection = 1
                    time.sleep(0.15)
                elif down.value() == 0 and set_selection == 1:
                    set_selection = 0
                    time.sleep(0.15)
                elif up.value() == 0 and set_selection == 1:
                    set_selection = 0
                    time.sleep(0.15)
                elif down.value() == 0 and set_selection == 0:
                    set_selection = 1
                    time.sleep(0.15)

            if record_button.value() == 0:
                pass
            else:
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
                else:
                    while select_button.value() != 0:
                        epd.clear(Color.WHITE)
                        epd.show_string(f"Volume : {percent_vol * 100}", 40, 40)
                        epd.update()

                        if up.value() == 0 and percent_vol != 1:
                            percent_vol = percent_vol + 0.02
                            time.sleep(0.02)
                        elif down.value() == 0 and percent_vol != 0:
                            percent_vol = percent_vol - 0.02
                            time.sleep(0.02)
                    
                    epd.clear(Color.WHITE)

        elif u_select == 3: #Group chat
            epd.clear()
            if gc_username is None or is_gc_username == False:
                wrap_text(epd, "Create a Username", 20, 20)
                percent = get_percent()
                draw_battery(epd, percent, epd.width - 40, 5)
                epd.update()
                time.sleep(0.1)
                while True:
                    now_time = time.time()
                    wrap_text(epd, "Record Your Username", 50, 50)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
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
                            
                    pre_txt = request_n_parse_translation(dev_ID)
                    gc_username = processing(pre_txt)
                    
                    draw_battery(epd, percent, epd.width - 40, 5)
                    wrap_text(epd, f"Set Username to {gc_username}?", 10, 10)
                    epd.update()
                    time.sleep(0.1)
                    wrap_text(epd, "Press 'Select' to Confirm", 20, 20)
                    wrap_text(epd, "Press 'Down' to Try Again", 30, 30)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
                    if select_button.value() == 0:
                        time.sleep(0.1)
                        epd.clear(Color.WHITE)
                        with open("gc_username.json", "w") as f:
                            json.dump(gc_username, f)
                        is_gc_username = True
                        break
                    elif down.value() == 0:
                        epd.clear(Color.WHITE)
                        continue
                    
            full_req = f"gc{gc_username}"
            my_id = dev_ID
            
            user_gc_choice = gc_UI(is_past_msg_sent)

            if user_gc_choice == 1 and is_past_msg_sent == True:
                while True:
                    now_time = time.time()
                    wrap_text(epd, "Record Your Message", 50, 50)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
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
                                
                    snd_txt = request_n_parse_translation(dev_ID)
                    msg = processing(snd_txt)
                        
                    draw_battery(epd, percent, epd.width - 40, 5)
                    wrap_text(epd, f"Send: {msg}?", 10, 10)
                    epd.update()
                    time.sleep(0.1)
                    wrap_text(epd, "Press 'Select' to Confirm", 20, 20)
                    wrap_text(epd, "Press 'Down' to Try Again", 30, 30)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
                    if select_button.value() == 0:
                        time.sleep(0.1)
                        epd.clear(Color.WHITE)
                        break
                    elif down.value() == 0:
                        epd.clear(Color.WHITE)
                        continue
                r = urequests.post(f"https://blog-skipping-send.ngrok-free.dev/gc?Request={full_req}&ID={dev_ID}&Message={msg}")
                sent_comf = r.json()

            elif user_gc_choice == 0 and is_past_msg_sent == False:
                while True:
                    now_time = time.time()
                    wrap_text(epd, "Record Your Message", 50, 50)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
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
                                
                    snd_txt = request_n_parse_translation(dev_ID)
                    msg = processing(snd_txt)
                        
                    draw_battery(epd, percent, epd.width - 40, 5)
                    wrap_text(epd, f"Send: {msg}?", 10, 10)
                    epd.update()
                    time.sleep(0.1)
                    wrap_text(epd, "Press 'Select' to Confirm", 20, 20)
                    wrap_text(epd, "Press 'Down' to Try Again", 30, 30)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.update()
                    if select_button.value() == 0:
                        time.sleep(0.1)
                        epd.clear(Color.WHITE)
                        break
                    elif down.value() == 0:
                        epd.clear(Color.WHITE)
                        continue

                r = urequests.post(f"https://blog-skipping-send.ngrok-free.dev/gc?Request={full_req}&ID={dev_ID}&Message={msg}")
                sent_comf = r.json()
            
            elif user_gc_choice == 0 and is_past_msg_sent == True:
                epd.clear(Color.WHITE)
                gc_letters = req_update("serv_letters")
                hist = req_update("prov_hist")
                for msg in hist:
                    msg["Message"] = ce.decipher(msg["Message"], gc_letters)
                
                msg_num = 0
                past_msg_num = None
                epd.show_string("Press 'Record' to go back", 20, 20)
                time.sleep(1)

                while record_button.value() != 0:
                    if past_msg_num != msg_num: #Prevents flickering and unecessary power loss
                        wrap_text(epd, f"{hist[msg_num]['Username']}: {hist[msg_num]['Message']}", 20, 10)
                        epd.update()

                    if up.value() == 0 and msg_num < len(hist) - 1:
                        msg_num = msg_num + 1
                        time.sleep(0.4)
                    elif down.value() == 0 and msg_num > 0:
                        msg_num = msg_num - 1
                        time.sleep(0.4)
                    #Exceptions
                    elif up.value() == 0 and msg_num >= len(hist) - 1:
                        msg_num = 0
                        time.sleep(0.4)
                    elif down.value() == 0 and msg_num <= 0:
                        msg_num = len(hist) - 1
                        time.sleep(0.4)

                    past_msg_num = msg_num
            else:
                continue
                
        elif u_select == 5: #Wait for any messages
            device = esp_network_client()
            device.client(use_message, percent_vol=percent_vol)
            machine.idle()

        if shut_off.value() == 0:
            time_off = time.time()
            while shut_off.value() == 0:
                machine.idle()
            if time.time() - time_off <= 1:
                pass
            else:
                shut_off_chime()
                time.sleep(0.2)
                machine.pin_sleep_wakeup([shut_off], machine.WAKEUP_ANY_HIGH)
                machine.deepsleep()
        elif percent < 45:
            epd.clear(Color.WHITE)
            epd.show_string(f"Charge The Device, it is at {percent}%", 30, 30)
            epd.update()
            time.sleep(2)
            while percent < 60:
                percent = get_percent()
                epd.show_string(f"Charge The Device, it is at {percent}%", 30, 30)
                epd.update()
                machine.idle()

    except Exception as e:
        epd.clear(Color.WHITE)
        wrap_text(epd, f"Error {e}", 50, 50)
        percent = get_percent()
        draw_battery(epd, percent, epd.width - 40, 5)
        epd.update()
        time.sleep(1)
        pass
            
