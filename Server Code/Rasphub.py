from flask import Flask, request, jsonify, render_template
from vosk import Model, KaldiRecognizer
import wave
import json
import random
import Cencrypt
from Crypto.Util import number
import math

#Flask server setup
app = Flask(__name__)
model = Model("models/vosk-model-small-en-us-0.15")

#Create all storage variables
gc_users = []
messg_hist = []
non_av_IDS = []
mailbox = []
pub_keys = {}

LETTERS = ["a","b","c","d","e","f","g","h","i","j","k","l","m","n","o","p","q","r","s","t","u","v","w","x","y","z"," ",
    "A","B","C","D","E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z",".",
    ",","/","[","]","`","~","\\","1","2","3","4","5","6","7","8","9","0","-","+","=","!","@","#","$","%","^","&",
    "*","(",")","<",">","?","|",";",";",":","'","\"","{","}"]

ALPH = LETTERS.copy()
random.shuffle(ALPH)

def get_param(key):
    """
    Helper function to handle values that are in json
    format, as .values.get will throw an error if it is
    a json. Otherwise it just uses .values.get.
    """
    if request.method == "POST" and request.is_json:
        return (request.get_json() or {}).get(key)
    return request.values.get(key)

@app.route("/stt", methods=["POST", "GET"])
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

@app.route("/gc", methods=["GET", "POST"])
def group_chat():
    """
    This allows the user to send messages in the group chat.
    It also shows the encrypted messages on the domain
    """

    global messg_hist

    req = get_param("Request") or ""
    if req[0:2] == "gc":
        user = {}
        user_name = req[2:]
        user["Username"] = user_name
        id = get_param("ID")
        user["ID"] = id
        gc_users.append(user)
        msg = get_param("Message")
        encrypted_msg_to_post, key = Cencrypt.cipher(msg, alphabet=ALPH)
        encrypted_msg_to_post = f"{key}{encrypted_msg_to_post}"
        entry = {} #Package to be stored in history
        entry["Username"] = user_name
        entry["Message"] = encrypted_msg_to_post

        #Update msg history
        messg_hist.append(entry)

        return jsonify(messg_hist)
    
    return render_template('web_msg.html')

@app.route("/messages")
def messages():
    global messg_hist
    return jsonify(messg_hist)

@app.route("/updates", methods=["GET", "POST"])
def prov_updates():
    """
    This function serves like a service for the device.
    The device can request for small actions.
    """
    global pub_keys

    req = get_param("Request")
    if req == "serv_letters":
        return jsonify(ALPH)
    elif req == "prov_hist":
        return jsonify(messg_hist)
    elif req == "check_mail":
        dev_ID = get_param("dev_id")
        messages = [{"destinationID": dest, "msg": msg, "senderID": sender, "type": mtype} 
                    for dest, msg, sender, mtype in mailbox if dest == dev_ID]
        mailbox[:] = [m for m in mailbox if m[0] != dev_ID]
        return jsonify(messages)
    elif req == "store_pub_key":
        pub_key = get_param("pub_key")
        reqester_id = get_param("senderID")
        e_str, n_str = pub_key.split("/")
        pub_keys[reqester_id] = {"e": int(e_str), "n": int(n_str)}
        return "stored"
    elif req == "get_cont_pub_key":
        cont_id = get_param("targ_id")
        if cont_id not in pub_keys:
            return jsonify({"error": "no key on file"}), 404
        return jsonify(pub_keys[cont_id])
    
@app.route("/getID", methods=['GET', 'POST'])
def get_ID():
    """
    This function assigns a device it's unique ID.
    The device sends a proposed ID, and if its available
    the server returns 'Clear' and logs the ID. 
    If it is not availble, the server generates/logs another one
    and sends that to the device.
    """
    global non_av_IDS

    requested_ID = get_param("req_ID")
    requested_ID = int(requested_ID)
    id_clear = False

    if requested_ID not in non_av_IDS:
        msg = "Clear"
        non_av_IDS.append(requested_ID)
        id_clear = True
        return jsonify(msg)
    else:
        while id_clear == False:
            id = random.randrange(100000000,999999999) #ID range
            if id not in non_av_IDS:
                id_clear = True
                return jsonify(id)

@app.route("/send-msg", methods=['GET', 'POST'])
def send_msg():
    """
    Simple function that stores the sender's message in the receiver's 
    'mailbox' based on ID.

    This can handle both text and audio messages
    """
    global mailbox

    msg = get_param("msg")
    msg_type = get_param("type")
    destintationID = get_param("destinationID")
    senderID = get_param("senderID")
    mailbox.append((destintationID, msg, senderID, msg_type))

    return "sent"

@app.route("/get_prime", methods=["POST", "GET"])
def get_large_prime():
    """
    Because the device itself cannot quickly generate 
    large 2048 prime numbers, it has the server generate
    them for the device's private and public key.
    """
    E = 65537
    while True:
        key1 = number.getPrime(2048)
        key2 = number.getPrime(2048)
        phi = (key1 - 1) * (key2 - 1)
        if math.gcd(E, phi) == 1:
            break
        
    d = pow(E, -1, phi)
    n = key1 * key2

    package = [f"{phi}/{d}/{n}/{key1}/{key2}"] #All info needed to create private and public keys
    return jsonify(package)

app.run(host="0.0.0.0", port=5000) #Run the server
