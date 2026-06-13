# Handcryption
A device that encrypts and sends/receives messages made from speech-to-text.
----------------------------------------------------------------------------


This device takes input from a microphone, then it sends the audio file to a Raspberry Pi server, where it converts the audio to text. This is sent back to the microcontroller, where it is then processed and encrypted using my Cencrypt library for the user to send to another device.
