"""
server.py - dpgonline server backend

Copyright (C) 2025 Deletecat

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
from sanic import Sanic, redirect, file
from sanic.exceptions import SanicException
from werkzeug.utils import secure_filename
from datetime import datetime
import magic
import re
import aiofiles
import encoder

app = Sanic("dpgonline")

class SilentError(SanicException):
    message = "Something went wrong,"
    quiet = True

@app.before_server_start
async def create_and_clear_directories(app,loop):
    # if we don't have an uploads folder, make it
    if not await aiofiles.ospath.exists("./uploads"):
        await aiofiles.os.mkdir("./uploads")
    # if we do, clear it's contents
    else:
        files = await aiofiles.os.scandir("./uploads")
        for f in files:
            await aiofiles.os.remove(f.path)

    # if we don't have a downloads folder, make it
    if not await aiofiles.ospath.exists("./downloads"):
        await aiofiles.os.mkdir("./downloads")
    # if we do, clear it's contents
    else:
        files = await aiofiles.os.scandir("./downloads")
        for f in files:
            await aiofiles.os.remove(f.path)

@app.post("/convert")
async def convert_video(request):
    # get input file and options
    input_filename, dpg_options = await upload_and_verify(request)

    # encode video
    await encoder.encode(dpg_options,input_filename)

    # send output video to user
    return await file(dpg_options.output,filename="output.dpg")

async def upload_and_verify(request):
    # get our file from the request
    input_file = request.files.get("file")
    # if there isn't a file, error out
    if not input_file:
        raise SilentError("File was not uploaded. Please try again.", status_code=400)

    # sanitise filename
    date_time = str(datetime.now())
    input_filename = "./uploads/" + date_time + "." + secure_filename(input_file.name).split(".")[-1]

    # check file mime type to ensure it's a video
    if not re.match(r"^video/.*",input_file.type):
        raise SilentError("Invalid file detected. Please try again.", status_code=400)
    elif len(input_file.body) > app.config.REQUEST_MAX_SIZE:
        # this should already be triggered by sanic, if not;
        raise SilentError("Your video is too big. Please compress your video before attempting to convert.", status_code=413)

    # write our video to file
    async with aiofiles.open(input_filename,"wb") as writer:
        await writer.write(input_file.body)

    # double-check video is indeed a video
    mime_type = magic.from_file(input_filename,mime=True)
    if not re.match(r"^video/.*",mime_type):
        await aiofiles.os.remove(input_filename)
        raise SilentError("Invalid file detected. Please try again.", status_code=400)

    # get dpg options
    dpg_options = encoder.DPGOpts(request.form.get("quality"),request.form.get("fps"),request.form.get("dpg"),request.form.get("width"),request.form.get("height"),request.form.get("aspect"))
    is_valid = dpg_options.verify_inputs()
    if not is_valid:
        raise SilentError("Invalid input detected. Please try again.", status_code=400)

    # set output filename
    dpg_options.output = "./downloads/" + date_time + ".dpg"

    return input_filename, dpg_options

@app.get("/favicon.ico")
async def send_favicon(request):
    return await file("./static/favicon.ico")

app.static("/","./static/index.html")
