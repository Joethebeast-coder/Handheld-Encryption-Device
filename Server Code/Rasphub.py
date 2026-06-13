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
        ip = request.values.get("IP")
        user["IP"] = ip
        gc_users.append(user)
        msg = request.values.get("Message")
        encrypted_msg_to_post = Cencrypt.cipher(msg, alphabet=ALPH)
        site_data["Username"] = user_name
        site_data["Message"] = encrypted_msg_to_post

        #Update msg history
        messg_hist.append(site_data.copy())

        return jsonify(messg_hist)
    
    return render_template('web_msg.html')

@app.route("/updates", methods=["GET"])
def prov_updates():
    req = request.form.get("Request")
    if req == "serv_letters":
        return jsonify(ALPH)
    elif req == "prov_hist":
        return jsonify(messg_hist)
    
app.run(host="0.0.0.0", port=5000)
