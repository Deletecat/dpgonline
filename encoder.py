"""
encoder.py - an async DPG encoder to be used with dpgonline
Derived from dpgconv with tweaks from my fork, dpgconv-py3

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

import asyncio
import aiofiles
import aiofiles.os
from PIL import Image
import struct
import re

class DPGOpts():
    def __init__(self, fps, dpg, width, height, keep_aspect):
        self.fps = fps
        self.dpg = dpg
        self.width = width
        self.height = height
        self.keep_aspect = keep_aspect
        self.output = "."

    def verify_inputs(self):
        valid = True # assume valid

        # check integer inputs are integers
        try:
            self.fps = int(self.fps)
            self.dpg = int(self.dpg)
            self.width = int(self.width)
            self.height = int(self.height)
        except (ValueError,TypeError):
            valid = False
        else:
            if self.fps <= 0 or self.fps > 24:
                valid = False
            elif self.dpg < 0 or self.dpg > 4:
                valid = False
            elif self.width <= 0 or self.width > 256:
                valid = False
            elif self.height <= 0 or self.height > 192:
                valid = False
            elif self.keep_aspect is not None and self.keep_aspect != "on":
                valid = False

        return valid

### encoder exception handling
class EncoderFailureException(Exception):
    def __init__(self,message):
        self.message = message
        super().__init__(self.message)

async def check_if_output_exists(file_name,stage):
    message = f"Encoding failed at {stage} stage. Please open an issue on GitHub or Codeberg." # initial base error
    try:
        file_size = await aiofiles.os.stat(file_name)
        file_size = int(file_size.st_size)
    except FileNotFoundError:
        raise EncoderFailureException(message)

    if file_size == 0:
        raise EncoderFailureException(message)

### conversion steps
async def convert_video(options,file,mpeg_1_temp):
    # get video data using ffprobe
    get_video_data = await asyncio.create_subprocess_exec("ffprobe", "-show_streams", file,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    # wait for process to complete and get output
    video_data = await get_video_data.communicate()
    frames = int(re.compile("avg_frame_rate=(.*)").search(video_data[0].decode("utf-8")).group(1).split("/")[0]) # find frame rate of the video

    # prevent user error if set fps is bigger than video fps
    if frames < options.fps:
        options.fps = frames

    if options.keep_aspect == "on":
        # calculate aspect ratio
        width = float(re.compile("width=(.*)").search(video_data[0].decode("utf-8")).group(1))
        height = float(re.compile("height=(.*)").search(video_data[0].decode("utf-8")).group(1))
        aspect_ratio = width/height

        if int(256.0/aspect_ratio) <= 192:
            options.width=256
            options.height=int(256.0/aspect_ratio)
        else:
            options.height=192
            options.width=int(aspect_ratio*192.0)
    pad_width = int((256-options.width)/2)
    pad_height = int((192-options.height)/2)

    proc = await asyncio.create_subprocess_exec("ffmpeg","-y","-i",file,"-f","data","-map","0:v:0","-r",str(options.fps),
                                                "-sws_flags","lanczos","-vf",f"scale={options.width}:{options.height},pad=256:192:{pad_width}:{pad_height}",
                                                "-codec:v","mpeg1video","-strict","experimental","-mbd","2",
                                                "-trellis","1","-mpv_flags","+cbp_rd","-mpv_flags","+mv0","-g","11",
                                                "-cmp","6","-subcmp","6","-precmp","6", "-dia_size","3","-pre_dia_size","3","-last_pred","3", mpeg_1_temp.name,
                                                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)

    await proc.wait()

    # error checking
    await check_if_output_exists(mpeg_1_temp.name,"video")

async def convert_audio(options,file,mpeg_2_temp):
    # get audio data
    get_audio_data = await asyncio.create_subprocess_exec("ffprobe", "-show_streams", file,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    # wait for process to complete and get output
    audio_data = await get_audio_data.communicate()

    # check to see if there are any audio streams
    channels = re.compile("channels=(.*)").search(audio_data[0].decode("utf-8"))

    if channels:
        # store the number of channels
        no_channels = int(channels.group(1))

        if no_channels >= 2 and options.dpg != 0:
            # run mencoder with twolame to get stereo, 2 channel audio
            proc = await asyncio.create_subprocess_exec("ffmpeg","-y","-i",file,"-f","data","-map","0:a:0","-codec:a","libtwolame","-ar","32000",
                                                        "-b:a","128k","-mode","stereo","-ac","2",mpeg_2_temp.name,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            # wait for process to complete
            await proc.wait()
        else:
            # run mencoder with twolame to get mono, 1 channel audio
            proc = await asyncio.create_subprocess_exec("ffmpeg","-y","-i",file,"-f","data","-map","0:a:0","-codec:a","libtwolame","-ar","32000",
                                                        "-b:a","128k","-mode","mono","-ac","1",mpeg_2_temp.name,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            # wait for process to complete
            await proc.wait()
    else:
        # This condition will only be true if the video does not have an audio stream.
        # Having no audio stream will crash Moonshell as it's expecting something that doesn't exist
        vid_length = re.compile("duration=([0-9]*.[0-9]*)").search(audio_data[0].decode("utf-8"))
        if vid_length:
            seconds = float(vid_length.group(1))
            proc = await asyncio.create_subprocess_exec("ffmpeg","-y","-f","lavfi","-i","anullsrc","-t",str(seconds),"-map","0:a:0","-codec:a","libtwolame",
                                                        "-b:a","128k","-mode","mono","-ac","1","-ar","32000",mpeg_2_temp.name,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            await proc.wait()
        else:
            pass # raise ERROR!

    # error checking
    await check_if_output_exists(mpeg_2_temp.name,"audio")

async def calculate_gop(options,file,mpeg_1_temp,gop_temp):
    """
    This is derived from dpgv4's gop calculation using ffprobe.
    All credits go to Pawel Slowik for this method!
    """
    frames = 0

    temp_gop_output = await aiofiles.tempfile.NamedTemporaryFile()
    # get ffprobe data and store it to a file
    async with aiofiles.open(temp_gop_output.name,"w") as writer:
        proc = await asyncio.create_subprocess_exec("ffprobe","-hide_banner","-print_format","csv","-show_frames","-select_streams","v",mpeg_1_temp.name,stdout=writer,stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()

    async with aiofiles.open(temp_gop_output.name,"r") as reader:
        if options.dpg >= 2:
            gop = await aiofiles.open(gop_temp.name,"wb")
        while True:
            line = await reader.readline()
            if line == "":
                break
            data = line.split(",")
            if data[0] != "frame":
                continue
            else:
                if options.dpg >= 2 and data[22] == "I":
                    await gop.write(struct.pack("<l",frames))
                    await gop.write(struct.pack("<l",int(data[12])))
                frames += 1

        if options.dpg >= 2:
            await gop.close()

    # error checking
    await check_if_output_exists(gop_temp.name,"gop")

    return frames

async def create_thumbnail(options,frames,thumb_temp,mpeg_1_temp):
    # create temp dir to store image in
    temp_dir = await aiofiles.tempfile.TemporaryDirectory()
    orig_thumb_file = temp_dir.name + "/00000001.png"

    # save a frame from the video as an image
    proc = await asyncio.create_subprocess_exec("ffmpeg","-ss",f"{int((int(frames)/options.fps)/10)}","-i",mpeg_1_temp.name,"-frames","1",orig_thumb_file,
                                                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)

    # wait for the process to complete
    await proc.wait()

    # error checking
    await check_if_output_exists(orig_thumb_file,"thumbnail (ffmpeg)")

    # original dpgconv thumbnail processing code
    im = Image.open(orig_thumb_file)
    width, height = im.size
    size = (256, 192)
    dest_w, dest_h = size

    if width * dest_h < height * dest_w:
        matrix=[ height/dest_h, 0.0, -(dest_w -(width*dest_h/height))//2,
                0.0, height/dest_h, 0.0 ]
    else:
        matrix=[ width/dest_w, 0.0, 0.0,
                0.0, width/dest_w, -(dest_h -(height*dest_w/width))//2 ]

    thumbim = im.transform(size, Image.AFFINE, matrix , Image.BICUBIC).getdata()

    data = []
    for i in range(dest_h):
        row = []
        for j in range(dest_w):
            red, green, blue = thumbim[i*dest_w+j][0], thumbim[i*dest_w+j][1], thumbim[i*dest_w+j][2]
            pixel = (( 1 << 15)
                | ((blue >> 3) << 10)
                | ((green >> 3) << 5)
                | (red >> 3))
            row.append(pixel)
        data.append(row)
    row_fmt=('H'*dest_w)
    thumb_data = b''.join(struct.pack(row_fmt, *row) for row in data)

    # write data to file
    async with aiofiles.open(thumb_temp.name,"wb") as writer:
        await writer.write(thumb_data)

    # error checking
    await check_if_output_exists(thumb_temp.name,"thumbnail (PIL)")

async def write_header(options,tempfiles,frames):
    audiostart=36
    if options.dpg == 1:
        audiostart += 4
    elif options.dpg == 2 or options.dpg == 3:
        audiostart += 12
    elif options.dpg == 4:
        audiostart += 98320

    # get audio/video stats
    audiosize = await aiofiles.os.stat(tempfiles[2].name)
    videosize = await aiofiles.os.stat(tempfiles[3].name)

    # replace the stats with size only
    audiosize = audiosize.st_size
    videosize = videosize.st_size

    videostart = audiostart + audiosize
    videoend = videostart + videosize

    pixel_format = 3    # "RGB24" - doesn't change anything really
    DPG = f"DPG{options.dpg}".encode("utf-8")

    headerValues = [ DPG, int(frames), options.fps, 0, 32000 , 0 ,int(audiostart), int(audiosize), int(videostart), int(videosize) ]

    # write header values
    async with aiofiles.open(tempfiles[0].name,"wb") as f:
        await f.write(struct.pack("4s", headerValues[0]))
        await f.write(struct.pack("<l", headerValues[1]))
        await f.write(struct.pack(">h", headerValues[2]))
        await f.write(struct.pack(">h", headerValues[3]))
        await f.write(struct.pack("<l", headerValues[4]))
        await f.write(struct.pack("<l", headerValues[5]))
        await f.write(struct.pack("<l", headerValues[6]))
        await f.write(struct.pack("<l", headerValues[7]))
        await f.write(struct.pack("<l", headerValues[8]))
        await f.write(struct.pack("<l", headerValues[9]))

        if options.dpg >= 2:
            # write gop if dpg version is 2+
            gopsize = await aiofiles.os.stat(tempfiles[4].name)
            gopsize = gopsize.st_size
            await f.write(struct.pack("<l", videoend))
            await f.write(struct.pack("<l", gopsize))

        if options.dpg != 0:
            # this must be added in dpg versions besides 0
            await f.write(struct.pack("<l", pixel_format))

        if options.dpg == 4:
            # indicate thumbnail in dpg 4
            await f.write(struct.pack("4s", b"THM0"))

    # error checking
    await check_if_output_exists(tempfiles[0].name,"header")

async def create_full_file(options,tempfiles):
    # open output dpg file
    async with aiofiles.open(options.output,"wb") as writer:
        # write each tempfile to the output file
        for data in tempfiles:
            async with aiofiles.open(data.name,"rb") as reader:
                await writer.write(await reader.read())

    # error checking
    await check_if_output_exists(options.output,"final")

async def encode(options,file):
    """
    temp files:
        0 - header
        1 - thumbnail
        2 - audio
        3 - video
        4 - GOP
    order was determined by DPG file structure
    """
    temporary_files = [
                       await aiofiles.tempfile.NamedTemporaryFile(suffix=".tmp"),
                       await aiofiles.tempfile.NamedTemporaryFile(suffix=".tmp"),
                       await aiofiles.tempfile.NamedTemporaryFile(suffix=".mp2"),
                       await aiofiles.tempfile.NamedTemporaryFile(suffix=".mpg"),
                       await aiofiles.tempfile.NamedTemporaryFile(suffix=".tmp")
                      ]

    # execute each step one by one
    await convert_video(options,file,temporary_files[3])
    await convert_audio(options,file,temporary_files[2])
    frames = await calculate_gop(options,file,temporary_files[3],temporary_files[4])

    # only dpg4 supported thumbnails
    if options.dpg == 4:
        await create_thumbnail(options,frames,temporary_files[1],temporary_files[3])
    await write_header(options,temporary_files,frames)

    if options.dpg < 2:
        # remove thumbnail and gop if dpg ver is 0 or 1
        temporary_files = [temporary_files[0],temporary_files[2],temporary_files[3]]
    elif options.dpg < 4:
        # remove thumbnail if dpg ver is 2 or 3
        temporary_files = [temporary_files[0],temporary_files[2],temporary_files[3],temporary_files[4]]

    await create_full_file(options,temporary_files) # done!
