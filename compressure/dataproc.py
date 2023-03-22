import logging
import subprocess
from pathlib import Path

from compressure.exceptions import InferredAttributeFromFileError, SubprocessError


logging.basicConfig(filename='.dataproc.log', level=logging.DEBUG)


def try_subprocess(command):
    process = subprocess.run(command, capture_output=True, encoding='utf-8')
    if process.returncode != 0:
        raise SubprocessError(process)
    return process


def reverse_video(fpath_in, fpath_out=None):
    """ Reverses video defined by fpath_in and writes to fpath_out if
        specified. If fpath_out isn't specified, it will be identical to
        fpath_in, but with "_reverse" appended to the end of the file name
        before the extension
    """
    fpath_in = Path(fpath_in).expanduser()
    if fpath_out is None:
        fpath_out = f"{fpath_in.parent / fpath_in.stem}_reverse{fpath_in.suffix}"
    else:
        fpath_out = Path(fpath_out).expanduser()

    command = [
        "ffmpeg",
        "-y",
        "-i", str(fpath_in),
        "-vf", "reverse",
        fpath_out
    ]
    try_subprocess(command)
    return fpath_out


def concat_videos(videos_list, fpath_out="output.avi"):
    input_videos = f"concat:{'|'.join(videos_list)}"
    command = [
        "ffmpeg", "-y",
        "-v", "error",
        "-i", input_videos,
        "-c:a", "copy",
        "-c:v", "copy",
        fpath_out
    ]
    try_subprocess(command)
    return fpath_out


def reverse_loop(fpath_in, fpath_out=None):
    fpath_in_ = Path(fpath_in)
    fpath_rev = str(Path(fpath_in).with_stem(fpath_in_.stem + "_pre-reverse").with_suffix(".avi"))
    reverse_video(fpath_in, fpath_rev)

    if fpath_out is None:
        fpath_out = str(Path(fpath_in).with_stem(fpath_in_.stem + "_reverse_loop").with_suffix(".avi"))

    concat_videos([fpath_in, fpath_rev], fpath_out)
    return fpath_out


def change_speed(fpath_in, fps_new, codec, fpath_out=None):
    fpath_in_ = Path(fpath_in)
    if fpath_out is None:
        fpath_out = str(fpath_in_.with_stem(f"{fpath_in_.stem}_{fps_new:.2f}"))
    # TODO pick up here
    if codec == 'h264':
        fpath_intermediate = "raw.h264"
        bitstream_filter = "h264_mp4toannexb"

    elif codec == 'h265':
        fpath_intermediate = "raw.h265"
        bitstream_filter = "hevc_mp4toannexb"
    else:
        raise ValueError(f"can only speed/slow h264- or h265-encoded videos, not {codec}")

    intermediate_command = [
        "ffmpeg", "-y",
        "-i", str(fpath_in_),
        "-map", "0:v",
        "-c:v", "copy",
        "-bsf:v", bitstream_filter,
        fpath_intermediate
    ]
    final_command = [
        "ffmpeg", "-y",
        "-fflags", "+genpts",
        "-r", str(fps_new),
        "-i", fpath_intermediate,
        "-c:v", "copy",
        fpath_out
    ]
    try_subprocess(intermediate_command)
    try_subprocess(final_command)

    return fpath_out


class VideoMetadata(object):
    """ Lazy metadata fetcher for videos
    """
    def __init__(self, fpath):
        self.fpath = fpath
        self._pix_fmt = None
        self._framerate_fractional = None
        self._framerate = self._fps = None
        self._height = None
        self._width = None
        self._duration = None
        self._codec = None

    @property
    def pix_fmt(self):
        if self._pix_fmt is None:
            command = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=pix_fmt",
                "-of", "csv=s=x:p=0",
                str(self.fpath)
            ]
            self._pix_fmt = try_subprocess(command).stdout.strip()

        #pix_fmt = process.stdout.read().decode("utf-8").strip()
        return self._pix_fmt

    @pix_fmt.setter
    def pix_fmt(self):
        raise InferredAttributeFromFileError(self.__name__, self.fpath)

    @property
    def framerate_fractional(self):
        if self._framerate_fractional is None:
            command = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=r_frame_rate",
                "-of", "csv=s=x:p=0",
                str(self.fpath)
            ]

            process = try_subprocess(command)

            self._framerate_fractional = [int(x) for x in process.stdout.split('/')]
        return self._framerate_fractional

    @framerate_fractional.setter
    def framerate_fractional(self):
        raise InferredAttributeFromFileError(self.__name__, self.fpath)

    @property
    def framerate(self):
        if self._framerate is None:
            self._framerate = self.framerate_fractional[0] / self.framerate_fractional[1]

        return self._framerate

    @framerate.setter
    def framerate(self):
        raise InferredAttributeFromFileError(self.__name__, self.fpath)

    @property
    def fps(self):
        return self.framerate

    @fps.setter
    def fps(self):
        raise InferredAttributeFromFileError(self.__name__, self.fpath)

    @property
    def dimensions(self):
        if self._height is None or self._width is None:
            command = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                str(self.fpath)
            ]
            process = try_subprocess(command)

            self._width, self._height = [int(x) for x in process.stdout.split('x')]

        return self._width, self._height

    @dimensions.setter
    def dimensions(self):
        raise InferredAttributeFromFileError(self.__name__, self.fpath)

    @property
    def height(self):
        if self._height is None:
            _, _ = self.dimensions

        return self._height

    @height.setter
    def height(self):
        raise InferredAttributeFromFileError(self.__name__, self.fpath)

    @property
    def width(self):
        if self._width is None:
            _, _ = self.dimensions

        return self._width

    @width.setter
    def width(self):
        raise InferredAttributeFromFileError(self.__name__, self.fpath)

    @property
    def duration(self):
        if self._duration is None:
            command = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=duration",
                "-of", "csv=s=x:p=0",
                str(self.fpath)
            ]
            self._duration = float(try_subprocess(command).stdout)

        return self._duration

    @property
    def codec(self):
        if self._codec is None:
            command = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(self.fpath)
            ]
            self._codec = try_subprocess(command).stdout.strip()
        return self._codec
