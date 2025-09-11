dpgonline
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

A DPG converter built to be hosted on the web.

Licensed under GPLv3 - see COPYING for more details.

REQUIREMENTS:
 + ffmpeg (with libtwolame support)
 + python3 with:
    + aiofiles
    + Jinja2
    + pillow
    + python-magic
    + sanic[ext]
    + werkzeug

You can run dpgonline locally using the command line below:

$ SANIC_REQUEST_MAX_SIZE=500000000 sanic server

You can change the request size value to match the maximum file size
you will permit. The above example is 500MB.

Enjoy :)

+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

CREDITS:

artm: dpgconv
+ initial encoder implementation was based around dpgconv with some
tweaks.

pawel-slowik: dpgv4
+ dpgv4 was a great reference when switching over to ffmpeg from
mplayer!
+ Video encoding command and GOP creation stage were mostly adapted
from here.

d0malaga, mpdavig, xukosky: dpg4x
+ documentation about the dpg format in dpg4x was quite helpful.
