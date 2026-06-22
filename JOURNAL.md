# Logs

## Hancryption Status Update 0.0.1
---------------------------------------
I have created the basic logic framework for the speech-to-text with processing. I am currently using many placeholders, however. Will be updating that by 0.0.4 at the latest. For encryption, I am using my previously developed “Cencrypt” Python library.
_____
### What’s Next in 0.0.2?
___
- Networking Framework
- Encryption Setup

<img width="1217" height="900" alt="image" src="https://github.com/user-attachments/assets/2829b4a2-be44-47e0-acb7-83bf51e57bb9" />

#

## Handcryption Status Update 0.0.1.5
---
### What’s New?
____
I created a rough sketch of the device. I also wrote down a tentative list of parts I would need. See Below
0.0.2 Should be released by 6/4/26.
___
*Note: I completely forgot about the screen and the parts needed for that.
E-ink display
6 buttons

<img width="1209" height="900" alt="image" src="https://github.com/user-attachments/assets/fe83efcd-3f38-4539-9262-03ea067de418" />

#

## Hancryption Status Update 0.0.2
---
### What Happened?
___
I added classes for server and client communication so the device could be either. I also added the encryption feature, which generates a unique key for each known IP address. The network also includes a client status check that occurs every 15 seconds, in which the client sends its IP address to the server.
___
### What’s Next in 0.0.3?
___
- Full draft code for a device. This will include all of the machine programming for the ESP32 chip, which is for the microphone, eink screen, and buttons.

- By 0.0.2.3, a draft parts list should be complete.

- By 0.0.2.5, a wiring diagram should be complete.

<img width="1260" height="900" alt="image" src="https://github.com/user-attachments/assets/96409c1b-b3e4-48e2-a659-7e7b22c66e9b" />

#

## Hancryption Status Update 0.0.2.1
---
### What Happened?
___
I patched some bugs in the client class so I could add a main loop for the device. When the device is sending, it is the server, and in any other circumstance, it is the client, it is idle and waiting for a message.
I added the button and microphone logic for the specific components.
I need to add the logic for the eink display

<img width="1035" height="900" alt="image" src="https://github.com/user-attachments/assets/96dec99d-f122-407d-abbb-fdb58ce66f6a" />

#

## Hancryption Status Update 0.0.3 (Combined)
______________________________________________
### What Happened in 0.0.2.3?
__________________________________________________________
I have created a parts list for this project:
Adafruit:
  - Adafruit Electret Microphone Amplifier - MAX4466 
              with Adjustable Gain
  - Adafruit 2.13" Monochrome eInk / ePaper Display 
              with SRAM - 250x122 Monochrome with SSD1680
  - Adafruit ESP32-S2 Feather - 4 MB Flash + 2 MB 
              PSRAM - STEMMA QT / Qwiic
  - Lithium Ion Polymer Battery - 3.7v 100mAh
  - Tactile Button switch (6mm) x 20 pack
  - Small Enclosed Piezo w/Wires
###
I have decided to use the Adafruit ESP32-S2 Feather as my microcontroller, as it takes care of the LiPoly battery charging, so I don't have to buy extra parts for it. I can also charge the battery through the USB-C on the board. It also has many GPIO pins that I can give to my e-Ink display, as well as the switches (6).
__________________________________________________________
### What Happened in 0.0.2.5?
__________________________________________________________
I created a wiring diagram for the components listed in the parts list. The time-lapse can be seen on Lapse*.

*I forgot to add the piezo in the time-lapse, and I wired the SDA and SCL pins to buttons, which was not supposed to happen, so later, I added the piezo, and moved the button wires to spare analog pins. You can see these in the screenshot below.
__________________________________________________________
### What Happened in 0.0.3?
__________________________________________________________
I made a complete draft of the code for the device. I added all of the button logic and basic e-ink display code. I added a loading screen with "HANCRYPTION" in block text and a sleep screen. To "power down", when the user holds the power button for more than 1 second, it goes into deep-sleep, which is basically off for microcontrollers. If it is less than that, it just goes idle. Of course, this is not the final code. I will keep adding more and more features that are compatible with the current set of parts I already have.
__________________________________________________________
### What's Next in 0.0.4?
__________________________________________________________
-Extra UI Features
-Possibility of Games

<img width="1017" height="900" alt="image" src="https://github.com/user-attachments/assets/9e1b2dfd-c371-48e8-a983-73e8e760762c" />
<img width="1241" height="900" alt="image" src="https://github.com/user-attachments/assets/08744b53-8700-4d89-ae33-8d6cf2f61645" />

#

## Handcryption Status Update 0.0.3.2 (Big News)
________________________________________________
### What Happened?
__________________________________________________________________________________
So, I was able to add in a UI that includes settings, contacts, message history, as well as battery status. In the settings, the user can change the volume of the piezo, as well as clear the files on their device (Contacts, Known IPs, and Message History. When hovering over a choice, the icon (the volume icon, for example) repeatedly switches from inverted to normal.
________________________________________________________________________________
However, while I was debugging, I found a MAJOR problem. My measly ESP32 microcontroller doesn't have enough CPU and RAM to run the speech-to-text model. However, I can pivot from this by using the VOSK model paired with my Raspberry Pi 4 that I have on hand as a server to run the model for the microcontroller. This opens up a whole new possibility. We can now have a main hub that monitors the devices, serves the speech-to-text requests, and sends the text back.
________________________________________________________________________________
### What's Next?
  - Speech-to-text code for the Raspberry Pi
  - Communication Protocol between the device and Pi

<img width="1136" height="900" alt="image" src="https://github.com/user-attachments/assets/da22ca7c-a33c-4ce8-975c-f51b30618580" />

#

## Handcryption Status Update 0.0.3.5
_____________________________________
### What Happened?
_____________________________________________________
I was able to set up a server on my Raspberry Pi 4 with the help of Copilot (I do not know Flask in the slightest). So now, when a device wants to send a message, the audio recording is sent to the Pi, requesting that it be translated to text. I've been experimenting with Claude on making a website to monitor the server's status, but I will talk about that more in a later update if I decide to go that route. 
__________________________________________________________
Today, I was able to make a CAD model of the housing of the device (The process of which is posted on Lapse). I have to admit, it looks a lot like the phreakers from the early days of calling. 
__________________________________________________________
### What's Next?
  - Decision on whether to pursue web monitoring
  - Preliminary BOM
  - Timeline Estimation
  - Extra Features for the Device

<img width="1394" height="900" alt="image" src="https://github.com/user-attachments/assets/8f8e3728-6bcc-451d-a1ee-78ca23dc5fdc" />

#

## Handcryption Status Update 0.0.3.6
_____________________________________
### What Happened?
__________________________________________________________
I added a cool new feature to the Handcryption device-GROUP CHATS!! This allows every user with a Handcryption device who opts to join the group to participate in conversations, fostering a more connected experience among users. I learned how to use Flask (thanks to GeeksforGeeks), which enabled me to seamlessly integrate the group chat feature into the server code running on the Raspberry Pi. 
__________________________________________________________
In addition to the chat functionality, there is now a website hosted on the Raspberry Pi's IP address that displays all the messages in the group chat. The caveat is that every message on the website is shown in its encrypted form to maintain security and confidentiality. 

__________________________________________________________
Looking ahead, I plan to implement a feature that would allow Handcryption users to sign in to the website. This will enable them to view messages in a decrypted format, enhancing user experience while still prioritizing privacy. I believe these developments will significantly improve user engagement and create a more dynamic platform for communication.

     My device(s) are becoming more and more like a phone

__________________________________________________________
### What's next?
__________________________________________________________
  - Preliminary BOM
  - Increase Website Functionality
  - Timeline Estimation
  - Code Cleanup and Extra Features
___
Photo Description: Some of the server code for the group chat
<img width="1019" height="900" alt="image" src="https://github.com/user-attachments/assets/90d87c2c-e4a9-4ca4-ad63-9ce2b05cb328" />

# 

## Handcryption Status Update 0.0.3.9
_____________________________________
## What Happened?
__________________________________________________________
Ok, big change to the workings of this device. Previously, this device could only work locally, but through my Raspberry Pi server and a domain through ngrok, I can make the device work on the cloud, and I have altered the server code and main device code to work this way. 
__________________________________________________________
Also, instead of using IPs to identify devices, I am using my own identification system that is like a phone number, a sequence of 9 digits. I recognize that this may be a small number of available sequences, but for now, it is a good amount. I can change this later.
__________________________________________________________
So, to send messages now, instead of using a socket, the device sends an HTTP request to the ngrok domain hosted by the Pi. The request includes the message, the destination's ID, and the sender's (the device's) ID. The server then stores this information in a "mailbox" -a collection of all sent messages. The receiving device, every 2 seconds, is sending an HTTP request to the server asking if there is anything in its mailbox. If so, the server returns the message(s) with the sender ID so the receiver can match that to a contact. 
__________________________________________________________
The cloud update has made my overall code length shorter, as most of the long sequences of code have been simplified to shorter HTTP requests.
__________________________________________________________
Also, as promised, this is my part BOM: https://github.com/Joethebeast-coder/Handheld-Encryption-Device/tree/main/Hardware
__________________________________________________________
## What's Next in 0.0.4?
__________________________________________________________
  - Extra Add-on Device Features
  - Maybe more website interactivity

<img width="929" height="900" alt="image" src="https://github.com/user-attachments/assets/aa5342d0-eb17-474f-8cc2-76fa4ff45c13" />

#

## Hancryption Status Update 0.0.4
____________________________________
### What Happened?
__________________________________________________________
So, I added in one last new feature to my code: voice messages. In order to play the audio, I have decided to ditch the piezo and use an actual speaker breakout, and I have updated the BOM on my Github as such (check the last devlog). 
__________________________________________________________
Other than that, I have been cleaning and debugging the code, and adding in comments; all to get it ready to request for funding. For some reason, my hackatime on the Stardance website isn't synced with what my Hackatime dashboard says. So, I'm posting this much eariler than I would have wanted in hopes to fix that issue.
__________________________________________________________
## What's Next?
- Sneak Peek at Funding Request Version
- Timeline

<img width="1539" height="900" alt="image" src="https://github.com/user-attachments/assets/4a2d7c4b-a186-44cc-a307-4e8ea7055bd9" />

#

## Handcryption Status Update 0.1
___________________________________
### What's Happening?
__________________________________________________________
So, I have been able to clean up everything in my code. I have added comments and the ability to connect to Wi-Fi. All of my code has been uploaded to GitHub for review for funding.
__________________________________________________________
Also on GitHub are my 3D models. Be aware that the part models' heights are an estimate based on the total height of the part given (if that makes sense). When printing the cover, I am planning to swap the filament from PLA to TPU to make the pads holding the buttons squishy.
__________________________________________________________
I am a little disappointed that the hackatime in my VS Code editor stopped recording time, and I lost 2 hours, but I will just use Lapse from now on. 
__________________________________________________________

<img width="1423" height="900" alt="image" src="https://github.com/user-attachments/assets/7347f298-aca3-45a8-ae78-af3ec918a43b" />

#
