import Cencrypt
import re
import speech_recognition as sr

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
    
new = processing(mic)
print(new)

#_____________________________________Networking + Encryption_________________________________________
LETTERS = ["a","b","c","d","e","f","g","h","i","j","k","l","m","n","o","p","q","r","s","t","u","v","w","x","y","z"," ",
    "A","B","C","D","E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z",".",
    ",","/","[","]","`","~","\\","1","2","3","4","5","6","7","8","9","0","-","+","=","!","@","#","$","%","^","&",
    "*","(",")","<",">","?","|",";",";",":","'","\"","{","}"]

