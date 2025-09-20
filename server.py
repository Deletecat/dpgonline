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
from sanic.log import logger
from sanic_ext import render
from werkzeug.utils import secure_filename
from datetime import datetime
import magic
import re
import asyncio
import aiofiles
import encoder

app = Sanic("dpgonline")

class SilentError(SanicException):
    message = "Possible user error - silent"
    quiet = True

class QueueObj():
    def __init__(self, id, ifn, dpgopts, lp, ip):
        self.id = id
        self.input_filename = ifn
        self.dpg_opts = dpgopts
        self.started = False # used to track the start of a job
        self.expiry_time = 0 # to be set once converted
        self.last_ping = lp # set once added to queue, used to make sure user is still in the queue/converting
        self.request_ip = ip # limit object to user IP
        self.failure_message = "N/A" # set failure error

### server init
@app.before_server_start
async def init_server(app,loop):
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

    # init queue
    app.ctx.dpg_queue = []
    app.ctx.dpg_converting = None
    app.ctx.dpg_downloadable = []
    app.ctx.failed_tasks = []
    app.ctx.current_id = 0

    # app version
    app.ctx.version = "v0.1-alpha1"

    # start background tasks
    app.add_task(download_cleanup)
    app.add_task(last_ping_cleanup)

    # success message!!
    logger.info("Server started successfully!")

### Background cleanup tasks
async def download_cleanup(app):
    # every 5 minutes, check to see if downloads have expired
    # if they have, remove them from the download list
    while True:
        await asyncio.sleep(300)
        logger.info("Starting download cleanup")
        if len(app.ctx.dpg_downloadable):
            cur_time = int(datetime.timestamp(datetime.now()))
            remove_list = []

            # loop through every available video and check to see if they've expired
            # if they have, remove them.
            for i in range(len(app.ctx.dpg_downloadable)):
                if app.ctx.dpg_downloadable[i].expiry_time < cur_time:
                    logger.info(f"Removing object {i} from downloads.")
                    await aiofiles.os.remove(app.ctx.dpg_downloadable[i].dpg_opts.output)   # delete video
                    remove_list.append(i)   # add it to the list of videos to remove
                else:
                    break

            # loop through the removal list and remove the videos from the download list
            if len(remove_list):
                for i in range(len(remove_list)):
                    app.ctx.dpg_downloadable.pop(remove_list[i])

async def last_ping_cleanup(app):
    # every 15 seconds, check to see if the user has left the site
    # if so, remove from queue (or conversion task section)
    while True:
        await asyncio.sleep(15)
        cur_time = int(datetime.timestamp(datetime.now()))
        remove_converting_task = False

        # if the conversion task hasn't started in the last 10 seconds, remove the task
        if app.ctx.dpg_converting and (cur_time - app.ctx.dpg_converting.last_ping) > 10 and not app.ctx.dpg_converting.started:
            remove_converting_task = True

        # check to see if users have been logged in the queue within the last 10 seconds, if not, remove their videos
        queue_removal = []
        for i in range(len(app.ctx.dpg_queue)):
            time_diff = cur_time - app.ctx.dpg_queue[i].last_ping # get time difference
            if time_diff > 10:
                await aiofiles.os.remove(app.ctx.dpg_queue[i].input_filename) # remove the input file
                queue_removal.append(i) # add to removal queue

        # remove all flagged videos from the queue
        for i in range(len(queue_removal)):
            logger.info(f"Removing object {i} from queue.")
            app.ctx.dpg_queue[i].pop(queue_removal[i])

        # if the conversion task hasn't started in the last 10 seconds, delete the input file
        # and set the task to none or the first queue object, whichever applies
        if(remove_converting_task):
            logger.info("Removing conversion task...")
            await aiofiles.os.remove(app.ctx.dpg_converting.input_filename)
            if len(app.ctx.dpg_queue):
                app.ctx.dpg_converting = app.ctx.dpg_queue[0]
                app.ctx.dpg_queue.pop(0)
            else:
                app.ctx.dpg_converting = None

### background encoding tasks
async def start_encoding(app):
    logger.info("Starting conversion task")
    try:
        await encoder.encode(app.ctx.dpg_converting.dpg_opts, app.ctx.dpg_converting.input_filename)
    except (encoder.EncoderFailureException,FileNotFoundError) as message:
        logger.info("Encoding task failed.")
        app.ctx.dpg_converting.failure_message = message
        app.ctx.failed_tasks.append(app.ctx.dpg_converting)
        # if there is a video in the queue, start the task
        if len(app.ctx.dpg_queue):
            app.ctx.dpg_converting = app.ctx.dpg_queue[0]
            app.ctx.dpg_queue.pop(0)
        else:
            app.ctx.dpg_converting = None
    else:
        # set download expiry and add to download list
        app.ctx.dpg_converting.expiry_time = int(datetime.timestamp(datetime.now())) + 1800 # downloads expire every half hour
        app.ctx.dpg_downloadable.append(app.ctx.dpg_converting)
        await aiofiles.os.remove(app.ctx.dpg_converting.input_filename)
        logger.info("Conversion task complete!")

        # if there is a video in the queue, start the task
        if len(app.ctx.dpg_queue):
            app.ctx.dpg_converting = app.ctx.dpg_queue[0]
            app.ctx.dpg_queue.pop(0)
        else:
            app.ctx.dpg_converting = None

### routing and functions
@app.get("/")
async def index(request):
    # template rendering to show version num and queue length on the home page
    return await render("index.html",context={"version":app.ctx.version,"queue_length":str(len(app.ctx.dpg_queue))},status=200)

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
    dpg_options = encoder.DPGOpts(request.form.get("fps"),request.form.get("dpg"),request.form.get("width"),request.form.get("height"),request.form.get("aspect"))
    is_valid = dpg_options.verify_inputs()
    if not is_valid:
        raise SilentError("Invalid input detected. Please try again.", status_code=400)

    # set output filename
    dpg_options.output = "./downloads/" + str(app.ctx.current_id) + ".dpg"

    dtn = datetime.timestamp(datetime.now())

    # add cookie to log user's video
    queue_obj = QueueObj(app.ctx.current_id,input_filename,dpg_options,dtn,request.remote_addr)

    # if there is a task being converted, add the user's upload to the queue
    # otherwise, start the conversion task
    if(app.ctx.dpg_converting):
        app.ctx.dpg_queue.append(queue_obj)
        response = redirect("/queue")
    else:
        app.ctx.dpg_converting = queue_obj
        response = redirect("/convert")

    # add the user's video id to a cookie
    response.add_cookie("video_id",str(app.ctx.current_id))
    app.ctx.current_id += 1

    return response

@app.get("/queue")
async def user_queue(request):
    # get video id from cookie (will fail if none is set)
    try:
        video_id = int(request.cookies.get("video_id"))
        queue_pos = await check_queue(video_id,True)
    except (ValueError,TypeError):
        return redirect("/")

    # if the video is not in the queue, redirect the user to where they need to be
    if not queue_pos:
        if app.ctx.dpg_converting is not None and app.ctx.dpg_converting.id == video_id:
            return redirect("/convert")
        elif await check_downloads(video_id,False):
            return redirect("/download")
        else:
            # no log of the video exists anywhere, so remove the video id cookie
            response = redirect("/")
            response.delete_cookie("video_id")
            return response
    # if the video exists, but the visitors IP does not match the uploaders,
    # remove the video id cookie and redirect to the homepage
    elif app.ctx.dpg_queue[queue_pos-1].request_ip != request.remote_addr:
        response = redirect("/")
        response.delete_cookie("video_id")
        return response

    app.ctx.dpg_queue[queue_pos-1].last_ping = datetime.timestamp(datetime.now())

    if queue_pos == 1:
        queue_pos = "1 - Next video to be converted"

    # send message to user with 5 second refresh
    return await render("queue.html",context={"queue_pos":str(queue_pos),"version":app.ctx.version,"queue_length":str(len(app.ctx.dpg_queue))},status=200)

@app.get("/convert")
async def convert_video(request):
    # get video id from cookie (will fail if none is set)
    try:
        video_id = int(request.cookies.get("video_id"))
    except (ValueError,TypeError):
        return redirect("/")

    # if the video is not being converted, redirect the user to where they need to be
    if app.ctx.dpg_converting is None or app.ctx.dpg_converting.id != video_id:
        if await check_failures(video_id,False):
            return redirect("/failure")
        elif await check_queue(video_id,False):
            return redirect("/queue")
        elif await check_downloads(video_id,False):
            return redirect("/download")
        else:
            # no log of the video exists anywhere, so remove the video id cookie
            response = redirect("/")
            response.delete_cookie("video_id")
            return response
    # if the video exists, but the visitors IP does not match the uploaders,
    # remove the video id cookie and redirect to the homepage
    elif app.ctx.dpg_converting.request_ip != request.remote_addr:
        response = redirect("/")
        response.delete_cookie("video_id")
        return response

    if not app.ctx.dpg_converting.started:
        # encode video
        app.add_task(start_encoding)
        app.ctx.dpg_converting.started = True

    app.ctx.dpg_converting.last_ping = datetime.timestamp(datetime.now())

    # send message to user with 5 second refresh
    return await render("convert.html",context={"version":app.ctx.version,"queue_length":str(len(app.ctx.dpg_queue))},status=200)

@app.get("/download")
async def download_content(request):
    # get video id from cookie (will fail if none is set)
    try:
        video_id = int(request.cookies.get("video_id"))
        download = await check_downloads(video_id,True)
    except (ValueError,TypeError):
        return redirect("/")

    # if the video is not a download, redirect the user to where they need to be
    if not download:
        if await check_queue(video_id,False):
            return redirect("/queue")
        elif app.ctx.dpg_converting is not None and app.ctx.dpg_converting.id == video_id:
            return redirect("/convert")
        else:
            # no log of the video exists anywhere, so remove the video id cookie
            response = redirect("/")
            response.delete_cookie("video_id")

    # if the video exists, but the visitors IP does not match the uploaders,
    # remove the video id cookie and redirect to the homepage
    elif app.ctx.dpg_downloadable[download-1].request_ip != request.remote_addr:
        response = redirect("/")
        response.delete_cookie("video_id")

    response = await file(app.ctx.dpg_downloadable[download-1].dpg_opts.output, filename=f"download{video_id}.dpg")
    response.delete_cookie("video_id")
    # send the file to the user
    return response

@app.get("/failure")
async def encoder_error_page(request):
    try:
        video_id = int(request.cookies.get("video_id"))
        failure = await check_failures(video_id,True)
    except (ValueError,TypeError):
        return redirect("/")

    response = None
    if not failure:
        response = redirect("/")
        response.delete_cookie("video_id")
    else:
        response = await render("error.html",
                                context={
                                        "error_message":app.ctx.failed_tasks[failure-1].failure_message,
                                        "version":app.ctx.version,
                                        "queue_length":str(len(app.ctx.dpg_queue))
                                    }
                                )
        response.delete_cookie("video_id")

    return response

# needed for the favicon to work
@app.get("/favicon.ico")
async def send_favicon(request):
    return await file("./static/favicon.ico")

# all errors go to the fancy page
@app.exception(Exception)
async def catch_all_errors(request, exception):
    return await render("error.html",context={"error_message":str(exception),"version":app.ctx.version,"queue_length":str(len(app.ctx.dpg_queue))})

### extra functions
async def check_queue(id,r_index):
    for i in range(len(app.ctx.dpg_queue)):
        if app.ctx.dpg_queue[i].id == id:
            if r_index:
                return i + 1
            else:
                return True
    return False

async def check_downloads(id, r_index):
    for i in range(len(app.ctx.dpg_downloadable)):
        if app.ctx.dpg_downloadable[i].id == id:
            if r_index:
                return i + 1
            else:
                return True
    return False

async def check_failures(id, r_index):
    for i in range(len(app.ctx.failed_tasks)):
        if app.ctx.failed_tasks[i].id == id:
            if r_index:
                return i + 1
            else:
                return True
    return False
