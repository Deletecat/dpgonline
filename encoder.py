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
import mmap
from PIL import Image
import struct
import re

class DPGOpts():
    def __init__(self, quality, fps, dpg, width, height, keep_aspect):
        self.quality = quality
        self.fps = fps
        self.dpg = dpg
        self.width = width
        self.height = height
        self.keep_aspect = keep_aspect
        self.output = "."

    def verify_inputs(self):
        valid = True # assume valid

        # valid input lists
        valid_quality_settings = ["low","normal","high"]

        # check integer inputs are integers
        try:
            self.fps = int(self.fps)
            self.dpg = int(self.dpg)
            self.width = int(self.width)
            self.height = int(self.height)
        except:
            valid = False
        else:
            if self.quality not in valid_quality_settings:
                valid = False
            elif self.fps <= 0 or self.fps > 60:
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

async def convert_video(options,file,mpeg_1_temp):
    # get video data using mplayer
    get_video_data = await asyncio.create_subprocess_exec("mplayer", "-frames", "1", "-vo", "null", "-ao", "null", "-identify", "-nolirc", file,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    # wait for process to complete and get output
    video_data = await get_video_data.communicate()
    frames = float(re.compile("ID_VIDEO_FPS=(.*)").search(video_data[0].decode("utf-8")).group(1)) # find number of frames in the video

    # prevent user error if set fps is bigger than video fps
    if frames < options.fps:
        options.fps = frames

    if options.keep_aspect == "on":
        # mplayer's video aspect ID doesn't always work so it's best to calculate it
        width = float(re.compile("ID_VIDEO_WIDTH=(.*)").search(video_data[0].decode("utf-8")).group(1))
        height = float(re.compile("ID_VIDEO_HEIGHT=(.*)").search(video_data[0].decode("utf-8")).group(1))
        aspect_ratio = width/height

        if int(256.0/aspect_ratio) <= 192:
            options.width=256
            options.height=int(256.0/aspect_ratio)
        else:
            options.height=192
            options.width=int(aspect_ratio*192.0)
    else:
        # use two ifs just in case both values are bigger than DS screen
        if options.width > 256:
            options.width = 256
        if options.height > 192:
            options.height = 192

    if options.quality == "high":
        # transcode video with high quality settings
        proc = await asyncio.create_subprocess_exec("mencoder", file, "-v", "-ofps", str(options.fps), "-sws", "9", "-vf",
                                             f"scale={options.width}:{options.height}:::3,expand=256:192,harddup", "-nosound", "-ovc", "lavc", "-lavcopts",
                                             f"vcodec=mpeg1video:vstrict=-2:mbd=2:trell:o=mpv_flags=+mv0:keyint=10:cmp=6:subcmp=6:precmp=6:dia=3:predia=3:last_pred=3:vbitrate=256",
                                             "-o", mpeg_1_temp.name, "-of", "rawvideo", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        # wait for transcoding to complete
        out = await proc.communicate()

    elif options.quality == "low":
        # transcode video with low quality settings
        proc = await asyncio.create_subprocess_exec("mencoder", file, "-v", "-ofps", str(options.fps), "-vf",
                                             f"scale={options.width}:{options.height},expand=256:192,harddup", "-nosound", "-ovc", "lavc", "-lavcopts",
                                             f"vcodec=mpeg1video:vstrict=-2:keyint=10:vbitrate=256", "-o", mpeg_1_temp.name, "-of",
                                             "rawvideo", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        # wait for transcoding to complete
        out = await proc.communicate()

    else:
        # transcode video with normal quality settings
        proc = await asyncio.create_subprocess_exec("mencoder", file, "-v", "-ofps", str(options.fps), "-sws", "9", "-vf",
                                             f"scale={options.width}:{options.height}:::3,expand=256:192,harddup", "-nosound", "-ovc", "lavc", "-lavcopts",
                                             f"vcodec=mpeg1video:vstrict=-2:keyint=10:mbd=2:trell:o=mpv_flags=+mv0:cmp=2:subcmp=2:precmp=2:vbitrate=256",
                                             "-o", mpeg_1_temp.name, "-of", "rawvideo", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        # wait for transcoding to complete
        out = await proc.communicate()

async def convert_audio(options,file,mpeg_2_temp):
    # get audio data using mplayer
    get_audio_data = await asyncio.create_subprocess_exec("mplayer", "-frames", "0", "-vo", "null", "-ao", "null", "nolirc", "-identify", file,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    # wait for process to complete and get output
    audio_data = await get_audio_data.communicate()

    # check to see if there are any audio channels - indicates audio stream
    channels = re.compile("([0-9]*)( ch)").search(audio_data[0].decode("utf-8"))

    if channels:
        # if there is an audio stream, store the number of channels
        no_channels = int(channels.group(1))

        if no_channels >= 2 and options.dpg != 0:
            # run mencoder with twolame to get stereo, 2 channel audio
            proc = await asyncio.create_subprocess_exec("mencoder",file,"-v","-of","rawaudio","-oac","twolame","-ovc","copy","-twolameopts","br=128:mode=stereo",
                                                            "-o", mpeg_2_temp.name, "-af", "channels=2,resample=32000:1:2",
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            # wait for process to complete
            out = await proc.communicate()
        else:
            # run mencoder with twolame to get mono, 1 channel audio
            proc = await asyncio.create_subprocess_exec("mencoder",file,"-v","-of","rawaudio","-oac","twolame","-ovc","copy","-twolameopts","br=128:mode=mono",
                                                            "-o", mpeg_2_temp.name, "-af", "channels=1,resample=32000:1:2",
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            # wait for process to complete
            out = await proc.communicate()
    else:
        # This condition will only be true if the video does not have an audio stream, or if mplayer errors out for some other reason.
        # Having no audio stream will crash Moonshell as it's expecting something that doesn't exist
        vid_length = re.compile("ID_LENGTH=([0-9]*.[0-9]*)").search(audio_data[0].decode("utf-8")) # ID_LENGTH corresponds to the video length in seconds
        if vid_length:
            seconds = float(vid_length.group(1))
            # use sox with the mp3 libsox format to generate a silent mp2 file
            proc = await asyncio.create_subprocess_exec("sox", "-n", "-r", "32000", "-c", "1", mpeg_2_temp.name, "trim", "0.0", str(seconds),
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out = await proc.communicate()
        else:
            pass # raise ERROR!

async def calculate_gop(options,file,mpeg_1_temp,gop_temp):
    """
    from mpeg_stat source and mpeg header reference:
        - picture start code: 0x00000100
        - sequence start code: 0x000001b3
        - GOP start code: 0x000001b8
    For every sequence, there's 10 pictures, due to the keyframe interval used during the transcoding stage being 10 frames.
    If the keyframe interval is tweaked, the for loop will have to be tweaked as well.
    These pictures continue to the end of the file, so if there's less than 10 pictures in a sequence (or no sequence after 10 pictures), we've reached EOF.
    Despite the GOP start code being a thing, DPG2+ doesn't seem to use it?
    """
    picture_start_code = b'\x00\x00\x01\x00'
    sequence_start_code = b'\x00\x00\x01\xb3'
    last_index = 0
    frames = 0

    async with aiofiles.open(mpeg_1_temp.name, "rb") as reader:
        # DPG2+ uses GOP for faster seeking
        if options.dpg >= 2:
            gop = await aiofiles.open(gop_temp.name,"wb")

        # use mmap so we don't have to read chunks of the video in
        file_mmap = mmap.mmap(reader.fileno(),0,access=mmap.ACCESS_READ)

        # loop until end of file reached
        while True:
            # check for the start of a sequence - returns -1 if EOF
            last_index = file_mmap.find(sequence_start_code,last_index)
            if(last_index == -1):
                break	# EOF
            elif options.dpg >= 2:
                # write info required for GOP if DPG2 or above
                await gop.write(struct.pack("<l",frames))
                await gop.write(struct.pack("<l",last_index))
            # increment last index so as to not find the same start code again
            last_index += 1

            # loop 10 times for each picture
            for i in range(10):
                # check if next picture exists - returns -1 if EOF
                last_index = file_mmap.find(picture_start_code,last_index)
                if(last_index == -1):
                    break	# EOF
                # increment frame counter and last index
                frames += 1
                last_index += 1

        # we need to close the GOP file manually
        if options.dpg >= 2:
            await gop.close()

    return frames

async def create_thumbnail(options,frames,thumb_temp,mpeg_1_temp):
    # create temp dir to store image in
    temp_dir = await aiofiles.tempfile.TemporaryDirectory()
    orig_thumb_file = temp_dir.name + "/00000001.png" # mplayer outputs the frame shot as 00000001.png

    # save a frame from the video as an image
    proc = await asyncio.create_subprocess_exec("mplayer", mpeg_1_temp.name, "-nosound", "-vo", f"png:outdir={temp_dir.name}", "-frames", "1", "-ss", f"{int((int(frames)/options.fps)/10)}",
                                                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)

    # wait for the process to complete
    out = await proc.communicate()

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

    pixel_format = 3
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

        if options.dpg != 1:
            # this must be added in dpg versions besides 1 for some reason
            await f.write(struct.pack("<l", pixel_format))

        if options.dpg == 4:
            # indicate thumbnail in dpg 4
            await f.write(struct.pack("4s", b"THM0"))

async def create_full_file(options,tempfiles):
    # open output dpg file
    async with aiofiles.open(options.output,"wb") as writer:
        # write each tempfile to the output file
        for data in tempfiles:
            async with aiofiles.open(data.name,"rb") as reader:
                await writer.write(await reader.read())

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
