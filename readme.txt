dpgonline
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

A DPG converter built to be hosted on the web.

Licensed under GPLv3 - see license.txt for more details.

REQUIREMENTS:
 + mplayer
 + mencoder
 + sox (with libsox-fmt-mp3)
 + python3 with:
    + pillow
    + aiofiles
    + sanic[ext]
    + werkzeug
    + python-magic

You can run dpgonline using the command line below:

SANIC_REQUEST_MAX_SIZE=5000000000 sanic server

You can change the request size value to match the maximum file size
you will permit. The above example is 5GB.

Enjoy :)

+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

CREDITS:

artm: dpgconv
    + Most of the encoding portion of dpgonline came from dpgconv.
pawel-slowik: dpgv4 // d0malaga, mpdavig, xukosky: dpg4x
    + These projects were a great reference as to how Moonshell's DPG
    format works. Major thanks to the devs!!
