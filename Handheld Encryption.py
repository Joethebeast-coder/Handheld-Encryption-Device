import Cencrypt as ce
import re
import speech_recognition as sr
import network
import time
import socket
import json
import os
import random
import machine

#_____________________________________Voice to Text______________________________________

r = sr.Recognizer() #Initialization

def convert_voice_to_text(file):
     with sr.AudioFile(file) as source:
          audio_data = r.record(source)
          text = r.recognize_ibm(audio_data)
          return text

#Get microphone input
mic = str(input(": ")) #Placeholder
#Put stuff here


#_____________________________________Processing_________________________________________

FILLER_WORDS = ["uh", "um", "uhh", "umm", "hmm", "uh,", "um,", "uhh,", "umm,", "hmm,"]
def processing(converted_text):
    words = converted_text.split()

    clean_words = [w for w in words if w not in FILLER_WORDS]
        
    processed_words = " ".join(clean_words)
    return processed_words
    
processed_txt = processing(mic)
print(processed_txt)

#_____________________________________Networking + Encryption_________________________________________
LETTERS = ["a","b","c","d","e","f","g","h","i","j","k","l","m","n","o","p","q","r","s","t","u","v","w","x","y","z"," ",
    "A","B","C","D","E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z",".",
    ",","/","[","]","`","~","\\","1","2","3","4","5","6","7","8","9","0","-","+","=","!","@","#","$","%","^","&",
    "*","(",")","<",">","?","|",";",";",":","'","\"","{","}"]

#Creates ip file
with open("known_ips.json", "w") as f:
    f.close

with open("my_letters.json", "w") as f:
    f.close

class esp_network_server:
    def __init__(self):
        #Networking Setup
        self.wlan = network.WLAN()
        self.wlan.active(True)
        self.wlan.scan()
        self.wlan.connect('ssid', 'key')
        self.wlan.config('windows')
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
        
    def run(self):
        while True:
            c, addr = self.s.accept()
            ip = addr[0]

            if ip not in self.known_ips:
                # First time this IP connects
                random.shuffle(LETTERS)
                self.known_ips[ip] = LETTERS.copy()

                # Send alphabet
                c.send(json.dumps(self.known_ips[ip]).encode("utf-8"))

                # Save updated known_ips
                with open(self.known_ips_path, "w") as f:
                    json.dump(self.known_ips, f)

            else:
                # Returning IP — load its saved alphabet
                LETTERS = self.known_ips[ip]

            #Start timer
            last_check = time.time()

            last_msg = None
            while True:
                #Check for incoming data
                c.settimeout(0.1)
                try:
                    data = c.recv(1024)
                    if data:
                        last_msg = data
                        client_msg = data.decode('utf-8')
                        print("Client says:", client_msg)
                except:
                    pass

                #Client check every 15 seconds
                if time.time() - last_check >= 15:
                    print("Running status check...")
                    status = self.cli_check(last_msg, ip)
                    last_check = time.time()

                    if not status:
                        print("Client failed status check. Closing.")
                        c.close()
                        break

                #Send encrypted message
                message = input("Enter anything: ")
                new_message, sent_key = ce.cipher(message, alphabet=LETTERS)
                combined_message = sent_key + new_message
                c.send(combined_message.encode("utf-8"))
                
                
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
        self.wlan = network.WLAN(network.WLAN.IF_STA)
        self.wlan.active(True)
        self.wlan.connect('ESP-AP')

        while not self.wlan.isconnected():
            time.sleep(0.1)
        
    
    def client(self):
        
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

        if LETTERS is None:
            data = s.recv(1024).decode("utf-8")
            LETTERS = json.loads(data)

            with open("my_letters.json", "w") as f:
                json.dump(LETTERS, f)
        
        msg = s.recv(1024)
        true_message = ce.decipher(msg, alphabet=LETTERS)

        packet = f"Received {cli_ip}"
        s.send(packet.encode('utf-8'))


#_____________________________________________Main__________________________________________________

