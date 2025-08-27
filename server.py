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
from sanic import Sanic, redirect, response, file, html, text
from sanic.exceptions import SanicException
from werkzeug.utils import secure_filename
from datetime import datetime
import magic
import re
import asyncio
import aiofiles
import encoder

app = Sanic("dpgonline")

class SilentError(SanicException):
    message = "Something went wrong,"
    quiet = True

class QueueObj():
    def __init__(self, id, ifn, dpgopts):
        self.id = id
        self.input_filename = ifn
        self.dpg_opts = dpgopts
        self.started = False # used to track the start of a job
        self.expiry_time = 0 # to be set once converted

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
    app.ctx.dpg_queue = []
    app.ctx.dpg_converting = None
    app.ctx.dpg_downloadable = []
    app.ctx.current_id = 0


async def download_cleanup():
    # every 5 minutes, check to see if downloads have expired
    # if they have, remove them from the download list
    while True:
        await asyncio.sleep(300)
        if(len(app.ctx.dpg_downloadable) > 0):
            cur_time = int(datetime.timestamp(datetime.now()))
            remove_list = []
            for i in range(len(app.ctx.dpg_downloadable)):
                if app.ctx.dpg_downloadable[i].expiry_time < cur_time:
                    aiofiles.os.remove(app.ctx.dpg_downloadable.dpg_opts.output)
                    remove_list.append(i)
                else:
                    break
            if(len(remove_list) > 0):
                for i in range(len(remove_list)):
                    app.ctx.dpg_downloadable.pop(remove_list[i])

@app.post("/upload")
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
    dpg_options.output = "./downloads/" + app.ctx.current_id + ".dpg"

    # add cookie to log user's video
    queue_obj = QueueObj(app.ctx.current_id,input_filename,dpg_options)

    if(app.ctx.dpg_converting):
        app.ctx.dpg_queue.append(queue_obj)
        response = redirect("/queue")
    else:
        app.ctx.dpg_converting = queue_obj
        response = redirect("/convert")

    response.add_cookie("video_id",str(app.ctx.current_id))
    app.ctx.current_id += 1

    return response

@app.get("/queue")
async def user_queue(request):
    video_id = int(request.cookies.get("video_id"))

    if app.ctx.dpg_converting is not None and app.ctx.dpg_converting.id == video_id:
        return redirect("/convert")
    elif not await check_queue(video_id,False):
        return redirect("/")

    # send message to user with 5 second refresh
    return html("""<!DOCTYPE html><html><head><title>dpgonline - queue</title><meta http-equiv="refresh" content="5">
        <style>body{font-family: sans-serif;background-color:#C3B1E1;padding:10px;}</style></head>
        <body><h1>You are currently in a queue.</h1><p>Please wait. Your media will be converted shortly.</p></body>""")

@app.get("/convert")
async def convert_video(request):
    video_id = int(request.cookies.get("video_id"))

    if app.ctx.dpg_converting == None or app.ctx.dpg_converting.id != video_id:
        if await check_queue(video_id,False):
            return redirect("/queue")
        elif await check_downloads(video_id,False):
            return redirect("/download")
        else:
            return redirect("/")

    if await aiofiles.os.path.exists(app.ctx.dpg_converting.dpg_opts.output):
        app.ctx.dpg_downloadable.append(app.ctx.dpg_converting)
        if len(app.ctx.dpg_queue) > 0:
            app.ctx.dpg_converting = app.ctx.dpg_queue[0]
            app.ctx.dpg_queue.pop(0)
        else:
            app.ctx.dpg_converting = None
        return redirect("/download")

    if not app.ctx.dpg_converting.started:
        # encode video
        app.add_task(encoder.encode(app.ctx.dpg_converting.dpg_opts, app.ctx.dpg_converting.input_filename))
        app.ctx.dpg_converting.started = True

    # send message to user with 5 second refresh
    return html("""<!DOCTYPE html><html><head><title>dpgonline - converting</title><meta http-equiv="refresh" content="5">
        <style>body{font-family: sans-serif;background-color:#C3B1E1;padding:10px;}</style></head>
        <body><h1>Your media is being converted.</h1><p>Please wait.</p></body>""")

@app.get("/download")
async def download_content(request):
    video_id = int(request.cookies.get("video_id"))
    download = await check_downloads(video_id,True)

    if download == False:
        if await check_queue(video_id,False):
            return redirect("/queue")
        elif app.ctx.dpg_converting is not None and app.ctx.dpg_converting.id == video_id:
            return redirect("/convert")
        else:
            return redirect("/")

    await aiofiles.os.remove(app.ctx.dpg_downloadable[download].input_filename)
    response = await file(app.ctx.dpg_downloadable[download].dpg_opts.output)
    response.delete_cookie("video_id")

    return response

@app.get("/favicon.ico")
async def send_favicon(request):
    return await file("./static/favicon.ico")

async def check_queue(id,r_index):
    for i in range(len(app.ctx.dpg_queue)):
        if app.ctx.dpg_queue[i].id == id:
            if r_index:
                return i
            else:
                return True
    return False

async def check_downloads(id, r_index):
    for i in range(len(app.ctx.dpg_downloadable)):
        if app.ctx.dpg_downloadable[i].id == id:
            if r_index:
                return i
            else:
                return True
    return False

app.static("/","./static/index.html")
app.add_task(download_cleanup())
