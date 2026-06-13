import Cencrypt as ce
import re
import network
import time
import utime
import socket
import json
import ujson
import os
import random
import urequests
import machine
from ssd1680 import SSD1680, Color
from machine import Pin, ADC, SPI, PWM, I2C

#_____________________________________IP helper__________________________________________

def get_device_ip():
    wlan = network.WLAN(network.WLAN.IF_STA)
    if wlan.isconnected():
        return wlan.ipconfig('addr4')

    ap = network.WLAN(network.WLAN.IF_AP)
    return ap.ipconfig('addr4')

#_____________________________________Button Setup_______________________________________

record_button = Pin(5, Pin.IN, Pin.PULL_UP) 
send_mes_button = Pin(15, Pin.IN, Pin.PULL_UP)
select_button = Pin(39, Pin.IN, Pin.PULL_UP)
up = Pin(8, Pin.IN, Pin.PULL_UP)
down = Pin(38, Pin.IN, Pin.PULL_UP)
shut_off = Pin(16, Pin.IN, Pin.PULL_UP)

#____________________________________Voltage Sensing_____________________________________

MAX17048_ADDR = 0x36

i2c = I2C(0, scl=Pin(4), sda=Pin(3))  

def read_register(reg):
    data = i2c.readfrom_mem(MAX17048_ADDR, reg, 2)
    return (data[0] << 8) | data[1]

def get_percent():
    raw = read_register(0x04)
    # Percentage is in 1/256% units
    return raw / 256

def draw_battery(epd, percent, x, y):
    percent = max(0, min(100, percent))
    
    width = 30
    height = 12
    nub_width = 3

    epd.draw_rectangle(x, y, x + width, y + height)

    epd.draw_rectangle(x + width, y + 3, x + width + nub_width, y + height - 3)

    fill_width = int((width - 4) * (percent / 100))

    for fy in range(y + 2, y + height - 1):
        epd.draw_line(x + 2, fy, x + 2 + fill_width, fy)

#______________________________________Piezo Setup_______________________________________

buzzer = PWM(Pin(14))

def notif_chime(buzzer_pin=buzzer, percent_vol=1):
    buzzer_pin.freq(3000)
    buzzer_pin.duty_u16(30000 * percent_vol)
    time.sleep(0.3)
    buzzer_pin.freq(2000)
    buzzer_pin.duty_u16(25000 * percent_vol)
    time.sleep(0.3)
    buzzer_pin.freq(1000)
    buzzer_pin.duty_u16(20000 * percent_vol)
    time.sleep(0.3)
    buzzer_pin.freq(3000)
    buzzer_pin.duty_u16(27000 * percent_vol) 
    time.sleep(0.3)
    buzzer_pin.deinit()

def handcryption_chime(buzzer_pin=buzzer, percent_vol=1):
    # (frequency, volume, duration)
    tones = [
        (1800, 28000 * percent_vol, 0.18),
        (1400, 24000 * percent_vol, 0.15), 
        (900, 20000 * percent_vol, 0.12), 
        (1600, 26000 * percent_vol, 0.15), 
        (2200, 30000 * percent_vol, 0.20),
        (2600, 32000 * percent_vol, 0.10)
    ]

    for freq, duty, duration in tones:
        buzzer_pin.freq(freq)
        buzzer_pin.duty_u16(duty)
        time.sleep(duration)

    buzzer_pin.deinit()

def wake_chime(buzzer_pin=buzzer, percent_vol=1):
    buzzer_pin.freq(1500)
    buzzer_pin.duty_u16(15000 * percent_vol)
    time.sleep(0.15)
    buzzer_pin.freq(3000)
    buzzer_pin.duty_u16(25000 * percent_vol)
    time.sleep(0.3)
    buzzer_pin.deinit()

def shut_off_chime(buzzer_pin=buzzer, percent_vol=1):
    buzzer_pin.freq(3000)
    buzzer_pin.duty_u16(30000 * percent_vol)
    time.sleep(0.15)
    buzzer_pin.freq(2000)
    buzzer_pin.duty_u16(20000 * percent_vol)
    time.sleep(0.15)
    buzzer_pin.freq(1000)
    buzzer_pin.duty_u16(10000 * percent_vol)
    buzzer_pin.deinit()
#______________________________________E-ink Setup_______________________________________

spi = SPI(
    2,
    baudrate=4000000,
    polarity=0,
    phase=0,
    sck=Pin(36),
    mosi=Pin(35),
    miso=Pin(37)   # not used by display
)

dc   = Pin(12, Pin.OUT)
busy = Pin(6, Pin.IN)
cs   = Pin(13, Pin.OUT)
res  = Pin(9, Pin.OUT)

epd = SSD1680(spi, dc, busy, cs, res)

epd.init()

epd.clear(Color.WHITE)

#_____________________________________Voice to Text______________________________________

adc = ADC(Pin(17)) 

SAMPLE_RATE = 8000        # 8 kHz audio
FILENAME = "recording.wav"

def write_wav_header(file, num_samples):
    file.write(b"RIFF")
    file.write((36 + num_samples).to_bytes(4, "little"))
    file.write(b"WAVEfmt ")
    file.write((16).to_bytes(4, "little"))
    file.write((1).to_bytes(2, "little"))      # PCM
    file.write((1).to_bytes(2, "little"))      # mono
    file.write(SAMPLE_RATE.to_bytes(4, "little"))
    file.write((SAMPLE_RATE * 2).to_bytes(4, "little"))
    file.write((2).to_bytes(2, "little"))      # block align
    file.write((16).to_bytes(2, "little"))     # bits per sample
    file.write(b"data")
    file.write(num_samples.to_bytes(4, "little"))

def collect_audio(samples):
    raw = adc.read_u16() >> 4          # 12‑bit sample
    samples.append(raw.to_bytes(2, "little"))
    utime.sleep_us(125)   

    return samples

def request_n_parse_translation():
    url = "http://192.168.1.254/stt"
    with open("recording.wav", "rb") as f:
        r = urequests.post(url, files={"file": f}, data={"Request" : "transl", "IP" : get_device_ip()})
    
    data = ujson.loads(r.text)
    text = data["text"]

    return text

    
#_____________________________________Processing_________________________________________

FILLER_WORDS = ["uhh", "umm", "hmm", "uh,", "um", "hm"]
def processing(converted_text, del_words=FILLER_WORDS):
    words = converted_text.split()

    clean_words = [w for w in words if w not in del_words]
        
    processed_words = " ".join(clean_words)
    return processed_words
    

#_____________________________________Networking + Encryption_________________________________________
LETTERS = ["a","b","c","d","e","f","g","h","i","j","k","l","m","n","o","p","q","r","s","t","u","v","w","x","y","z"," ",
    "A","B","C","D","E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z",".",
    ",","/","[","]","`","~","\\","1","2","3","4","5","6","7","8","9","0","-","+","=","!","@","#","$","%","^","&",
    "*","(",")","<",">","?","|",";",";",":","'","\"","{","}"]

#Creates json files
if not os.path.exists("known_ips.json"):
    with open("known_ips.json", "w") as f:
        f.close

if not os.path.exists("my_letters.json"):
    with open("my_letters.json", "w") as f:
        f.close

if not os.path.exists("contacts.json"):
    with open("contacts.json", "w") as f:
        f.close

if not os.path.exists("history.json"):
    with open("history.json", "w") as f:
        f.close

class esp_network_server:
    def __init__(self):
        self.running = True
        #Networking Setup
        self.wlan = network.WLAN()
        self.wlan.active(True)
        self.wlan.scan()
        self.wlan.connect('ssid', 'key')
        hIP = self.wlan.ipconfig('addr4') #Variable for host IP

        self.ap = network.WLAN(network.WLAN.IF_AP)
        self.ap.config(ssid='ESP-AP')
        self.ap.config(max_clients=15) #15 is the max amount of people that can connect
        self.ap.active(True)

        #Connection
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        port = 40675
        self.s.bind((hIP, port))
        self.s.listen(3)

        self.known_ips_path = "known_ips.json"
        self.known_ips = self.load_known_ips()

        self.contacts_path = "contacts.json"
        if os.path.exists(self.contacts_path):
            with open(self.contacts_path, "r") as f:
                self.contacts = json.load(f)
        else:
            self.contacts = {}

        self.message_to_send = ""

    def load_known_ips(self):
        # Load known IPs properly
        if os.path.exists(self.known_ips_path):
            try:
                with open(self.known_ips_path, "r") as f:
                    return json.load(f)
            except:
                return {}
        else:
            return {}
        
    def run(self, get_message, target_ip, contact):
        self.clients = {}
        self.target_ip = target_ip

        while self.running:
            c, addr = self.s.accept()
            ip = addr[0]

            self.clients[ip] = {
                "socket": c,
                "letters": LETTERS
            }

            if ip not in self.known_ips:

                wrap_text(epd, f"New device: {ip}. Enter a contact name: ", 20, 20)
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
                    
                    txt = request_n_parse_translation()
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
                self.contacts[name_] = ip

                with open(self.contacts_path, "w") as f:
                    json.dump(self.contacts, f)

                #First time this IP connects, give their key
                random.shuffle(LETTERS)
                self.known_ips[ip] = LETTERS.copy()

                # Send alphabet
                c.send(json.dumps(self.known_ips[ip]).encode("utf-8"))

                # Save updated known_ips
                with open(self.known_ips_path, "w") as f:
                    json.dump(self.known_ips, f)

            client_letters = self.known_ips[ip]

            self.clients[ip] = {
                "socket": c,
                "letters": client_letters
            }

            #Start timer
            last_check = time.time()

            last_msg = None
            while self.running:
                #Check for incoming data
                c.settimeout(0.1)
                try:
                    data = c.recv(1024)
                    if data:
                        last_msg = data
                        client_msg = data.decode('utf-8')

                        if self.message_to_send == "Closing Server":
                            if "rec-close" in client_msg and ip in client_msg:
                                time.sleep(0.1)
                                c.close()
                                self.running = False
                            else:
                                time.sleep(3)
                                if "rec-close" in client_msg and ip in client_msg:
                                    time.sleep(0.1)
                                    c.close()
                                    self.running = False 
                except:
                    pass

                #Client check every 15 seconds
                if time.time() - last_check >= 15:
                    status = self.cli_check(last_msg, ip)
                    last_check = time.time()

                    if not status:
                        epd.clear(Color.WHITE)
                        percent = get_percent()
                        draw_battery(epd, percent, epd.width - 40, 5)
                        epd.show_string("Client disconnected", 20, 20)
                        epd.update()
                        c.close()
                        self.running = False

                #Send encrypted message
                message = get_message()
                
                target = self.clients.get(self.target_ip)
                if not target:
                    epd.clear(Color.WHITE)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    epd.show_string("Client not connected", 20, 20)
                    epd.update()
                    continue

                sock = target["socket"]
                letters = target["letters"]

                if message == "Closing Server":
                    self.message_to_send = "Closing Server"
                    sock.send(self.message_to_send.encode())
                    continue

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
                
                history.append({"To" : contact, "IP" : target_ip, "Time" : time.time(), "Message" : message, "Cencrypted Message" : combined_message})
                with open("history.json", "w") as f:
                    json.dump(history, f)
            
                epd.show_string("Sending...", 20, 20)
                percent = get_percent()
                draw_battery(epd, percent, epd.width - 40, 5)
                epd.update()
                sock.send(combined_message.encode("utf-8"))
                time.sleep(0.5)
                epd.clear(Color.WHITE)
                epd.show_string("Sent", 20, 20)
                percent = get_percent()
                draw_battery(epd, percent, epd.width - 40, 5)
                epd.update()                
                time.sleep(0.5)
                self.running = False
                
    def cli_check(self, last_msg, ip):
        if last_msg is None:
            return False
        
        try:
            msg = last_msg.decode('utf-8')
        except:
            msg = str(last_msg)
        
        return ip in msg



class esp_network_client:

    def __init__(self):
        self.running = True
        self.wlan = network.WLAN(network.WLAN.IF_STA)
        self.wlan.active(True)
        self.wlan.connect('ESP-AP')

        while not self.wlan.isconnected():
            time.sleep(0.1)
        
    
    def client(self, out_message, percent_vol):
        try:
            if os.path.exists("my_letters.json"):
                with open("my_letters.json", "r") as f:
                    data = f.read().strip()
                    if data:
                        LETTERS = json.loads(data)
                    else:
                        LETTERS = None
                
            server_ip = '192.168.4.1'
            server_port = 40675
            cli_ip = self.wlan.ipconfig('addr4')

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((server_ip, server_port))
            s.send(cli_ip.encode())
            
            timer = time.time()
            
            if LETTERS is None:
                data = s.recv(1024).decode("utf-8")
                LETTERS = json.loads(data)

                with open("my_letters.json", "w") as f:
                    json.dump(LETTERS, f)
            
            while self.running:
                msg = s.recv(1024)
                if msg.decode() == "Closing Server":
                    s.send(f"rec-close : {cli_ip}")
                    s.close()
                    self.running = False

                true_message = ce.decipher(msg, alphabet=LETTERS)
                notif_chime(percent_vol=percent_vol)
                out_message(true_message)

                if time.time() - timer >= 15:
                    packet = f"Received {cli_ip}"
                    s.send(packet.encode('utf-8'))
                    timer = time.time()
        except:
            return None



#_____________________________________________Main__________________________________________________

def wrap_text(epd, text, x, y, max_width=250, font_width=6, line_height=10):
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

def get_processed_message():
    return processed_txt

def use_message(decoded_msg):
    epd.clear(Color.WHITE)
    wrap_text(epd, f"Message: {decoded_msg}", 20, 20)
    percent = get_percent()
    draw_battery(epd, percent, epd.width - 40, 5)
    epd.update()

def render_block_text(text, width, height):
    # 5x7 block font for A–Z and 0–9
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

    # Build raw 7-row text pattern
    rows = [[] for _ in range(7)]
    for ch in text:
        pattern = FONT.get(ch.upper(), ["00000"] * 7)
        for i in range(7):
            rows[i] += [int(x) for x in pattern[i]] + [0]  # 1-pixel spacing

    # Scale to target width/height
    scale_x = max(1, width // len(rows[0]))
    scale_y = max(1, height // len(rows))

    bitmap = []
    for row in rows:
        scaled_row = []
        for pixel in row:
            scaled_row += [pixel] * scale_x
        for _ in range(scale_y):
            bitmap.append(scaled_row[:width])  # trim to exact width

    return bitmap[:height]  # trim to exact height

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
        
def gc_req_update(request):
    r = urequests.get("http://192.168.1.254/updates?Request=request")
    data = r.json()

    return data

handcryption_bitmap = render_block_text("HANDCRYPTION", 220, 30)
recording_bitmap = render_block_text("RECORDING", 220, 30)
tap_bitmap = render_block_text("Press a Button to Continue", 220, 30)
x_start = (epd.width - 220) // 2
y_start = (epd.height - 30) // 2

percent_vol = 1
epd.show_bitmap(handcryption_bitmap, x_start, y_start)
epd.update()
percent = get_percent()
draw_battery(epd, percent, epd.width - 40, 5)
handcryption_chime(percent_vol=percent_vol)

gc_username = None
is_past_msg_sent = False

while True:
    try:
        epd.show_bitmap(tap_bitmap, x_start, y_start)
        epd.update()
        while select_button.value() == 1 and down.value() == 1 and up.value() == 1 and send_mes_button.value() == 1 and record_button.value() == 1:
            machine.idle()

        wake_chime(percent_vol=percent_vol)
        epd.clear(Color.WHITE)
        time.sleep(0.2)
        percent = get_percent()
        draw_battery(epd, percent, epd.width - 40, 5)
        epd.update()
        time.sleep(0.3)
        u_select = UI()
        if u_select == 4:
            epd.clear(Color.WHITE)
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
                txt = request_n_parse_translation()
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
                    
            if cont_num == None:
                u_select = 1
                continue
            else:
                target_name = contact_list[cont_num]
                target_ip = contacts[target_name]
                device = esp_network_server()
                device.run(get_processed_message, target_ip, target_name)

        elif u_select == 0:
            #History
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

        elif u_select == 1:
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
                            
                            txt = request_n_parse_translation()
                            processed_txt = processing(txt)

                            epd.clear(Color.WHITE)
                            now_time = time.time()
                            wrap_text(epd, "Record the IP", 50, 50)
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
                            
                            txt = request_n_parse_translation()
                            ip = processing(txt)

                            epd.clear(Color.WHITE)
                            time.sleep(0.1)
                            percent = get_percent()
                            draw_battery(epd, percent, epd.width - 40, 5)
                            wrap_text(epd, f"Set IP to {ip}?", 10, 10)
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
                        contacts[name_] = ip

                        with open("contacts.json", "w") as f:
                            json.dump(contacts, f)

            else:
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
                            
                    txt = request_n_parse_translation()
                    processed_txt = processing(txt)

                    epd.clear(Color.WHITE)
                    now_time = time.time()
                    wrap_text(epd, "Record the IP", 50, 50)
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
                            
                    txt = request_n_parse_translation()
                    ip = processing(txt)

                    epd.clear(Color.WHITE)
                    time.sleep(0.1)
                    percent = get_percent()
                    draw_battery(epd, percent, epd.width - 40, 5)
                    wrap_text(epd, f"Set IP to {ip}?", 10, 10)
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
                contacts[name_] = ip

                with open("contacts.json", "w") as f:
                    json.dump(contacts, f)
        
        elif u_select == 2:
            x_left  = 3
            x_right = 234
            y_mid   = 54

            epd.clear(Color.WHITE)
            epd.show_string("Press 'Record' to go back")
            epd.update()
            time.sleep(1)
            epd.clear(Color.WHITE)
            epd.show_bitmap(icons["Reset"], x_left, y_mid)
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
                    
                    with open("known_ips.json", "w") as f:
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

        elif u_select == 3:
            epd.clear()
            if gc_username is None:
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
                            
                    pre_txt = request_n_parse_translation()
                    gc_username = processing(txt)
                    
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
                        break
                    elif down.value() == 0:
                        epd.clear(Color.WHITE)
                        continue
                    
            full_req = f"gc{gc_username}"
            my_ip = get_device_ip()
            
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
                                
                    snd_txt = request_n_parse_translation()
                    msg = processing(txt)
                        
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
                r = urequests.post("http://192.168.1.254/gc?Request=full_req&IP=my_ip&Message=msg")
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
                                
                    snd_txt = request_n_parse_translation()
                    msg = processing(txt)
                        
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

                r = urequests.post("http://192.168.1.254/gc?Request=full_req&IP=my_ip&Message=msg")
                sent_comf = r.json()
            
            elif user_gc_choice == 0 and is_past_msg_sent == True:
                epd.clear(Color.WHITE)
                gc_letters = gc_req_update("serv_letters")
                hist = gc_req_update("prov_hist")
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

            else:
                continue
                
        elif u_select == 5:
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
            
