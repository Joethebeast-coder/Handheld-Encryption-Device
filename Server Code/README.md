Quick Overview
---------------------------------------------------------
This is the server code that will run on a Raspberry Pi 4

How it works
----------------------------------------------------------------
It uses Flask to create an HTTP server where the microcontroller
can make requests.

Types of Requests
    1. Speech-to-text
        The microcontroller cannot run the speech-to-text API on its own, so it makes
        a request to the server to convert an audio file.
    2. Group Chat
        The microcontroller can connect to a group chat that is between every user. This
        section allows the microcontroller to send messages in the group chat
    3. Updates
        The microcontroller can request updates from the server, such as the server's set of letters
        used to encrypt the messages of the group chat, as well as its message history.
