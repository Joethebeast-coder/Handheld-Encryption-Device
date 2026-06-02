import random

LETTERS = ["a","b","c","d","e","f","g","h","i","j","k","l","m","n","o","p","q","r","s","t","u","v","w","x","y","z"," ",
    "A","B","C","D","E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z",".",
    ",","/","[","]","`","~","\\","1","2","3","4","5","6","7","8","9","0","-","+","=","!","@","#","$","%","^","&",
    "*","(",")","<",">","?","|",";",";",":","'","\"","{","}"]

# ------------------ FIXED: index_find uses the correct alphabet ------------------
def index_find(key, alphabet):
    for idx, char in enumerate(alphabet):
        if char == key:
            return idx
    return -1

# ------------------ FIXED: cipher always uses the passed alphabet ------------------
def cipher(message, alphabet=LETTERS):
    if not message:
        return "", alphabet[0]

    # pick a random character from the message as the key
    num = random.randint(0, len(message) - 1)
    key = message[num]
    j = index_find(key, alphabet)

    # convert message to indexes
    split_letters = [index_find(c, alphabet) for c in message]

    # shift indexes
    for i in range(len(split_letters)):
        split_letters[i] = (split_letters[i] + j) % len(alphabet)

    # convert back to characters
    new_message = "".join(alphabet[i] for i in split_letters)

    # send the key character (alphabet[j])
    sent_key = alphabet[j]

    return new_message, sent_key

# ------------------ FIXED: decipher always uses the passed alphabet ------------------
def decipher(message, alphabet=LETTERS):
    if not message:
        return ""

    # first character is the key
    key = message[0]
    j = index_find(key, alphabet)

    # rest is the encrypted text
    cipher_text = message[1:]

    # convert to indexes
    split_ciphered = [index_find(c, alphabet) for c in cipher_text]

    # reverse the shift
    for i in range(len(split_ciphered)):
        split_ciphered[i] = (split_ciphered[i] - j) % len(alphabet)

    # convert back to characters
    deciphered_message = "".join(alphabet[i] for i in split_ciphered)

    return deciphered_message

