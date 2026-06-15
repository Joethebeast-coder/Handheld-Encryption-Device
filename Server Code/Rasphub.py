from flask import Flask, request, jsonify, render_template
from vosk import Model, KaldiRecognizer
import wave
import json
import psutil
import time
import os
import subprocess
import random
import Cencrypt

app = Flask(__name__)
model = Model("models/vosk-model-small-en-us-0.15")

gc_users = []
site_data = {}
messg_hist = []
non_av_IDS = []
mailbox = []

LETTERS = ["a","b","c","d","e","f","g","h","i","j","k","l","m","n","o","p","q","r","s","t","u","v","w","x","y","z"," ",
    "A","B","C","D","E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z",".",
    ",","/","[","]","`","~","\\","1","2","3","4","5","6","7","8","9","0","-","+","=","!","@","#","$","%","^","&",
    "*","(",")","<",">","?","|",";",";",":","'","\"","{","}"]

ALPH = LETTERS.copy()
random.shuffle(ALPH)

@app.route("/stt", methods=["POST"])
def stt():
    req = request.form.get("Request")
    if req == "transl":
        audio = request.files["file"]
        audio.save("temp.wav")

        wf = wave.open("temp.wav", "rb")
        rec = KaldiRecognizer(model, wf.getframerate())

        text = ""
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                text = json.loads(rec.Result())["text"]

        final = json.loads(rec.FinalResult())["text"]
        return jsonify({"text": final})

@app.route("/messages", methods=["GET"])
def messages():
    return jsonify(messg_hist)

@app.route("/gc", methods=["GET", "POST"])
def group_chat():
    global site_data
    global messg_hist

    req = request.values.get("Request")
    if req[0:2] == "gc":
        user = {}
        user_name = req[2:]
        user["Username"] = user_name
        id = request.values.get("ID")
        user["ID"] = id
        gc_users.append(user)
        msg = request.values.get("Message")
        encrypted_msg_to_post, key = Cencrypt.cipher(msg, alphabet=ALPH)
        encrypted_msg_to_post = f"{key}{encrypted_msg_to_post}"
        site_data["Username"] = user_name
        site_data["Message"] = encrypted_msg_to_post

        #Update msg history
        messg_hist.append(site_data.copy())

        return jsonify(messg_hist)
    
    return render_template('web_msg.html')

@app.route("/updates", methods=["GET"])
def prov_updates():
    req = request.values.get("Request")
    if req == "serv_letters":
        return jsonify(ALPH)
    elif req == "prov_hist":
        return jsonify(messg_hist)
    elif req == "check_mail":
        dev_ID = request.values.get("dev_id")
        messages = [msg for dest, msg in mailbox if dest == dev_ID]
        return jsonify(messages)

@app.route("/getID", methods=['GET', 'POST'])
def get_ID():
    global non_av_IDS

    requested_ID = request.values.get("req_ID")
    id_clear = False

    if requested_ID not in non_av_IDS:
        msg = "Clear"
        non_av_IDS.append(requested_ID)
        id_clear = True
        return jsonify(msg)
    else:
        while id_clear == False:
            id = random.randrange(100000000,999999999)
            if id not in non_av_IDS:
                id_clear = True
                return jsonify(id)

@app.route("/send-msg", methods=['GET', 'POST'])
def send_msg():
    global mailbox

    msg = request.values.get("msg")
    destintationID = request.values.get("destinationID")

    mailbox.append((destintationID, msg))

    return "sent"

app.run(host="0.0.0.0", port=5000)
