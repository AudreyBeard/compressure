import logging
import os
from pathlib import Path
import subprocess
from typing import Sequence

from compressure.exceptions import InferredAttributeFromFileError, SubprocessError


logging.basicConfig(filename='.dataproc.log', level=logging.DEBUG)


def try_subprocess(
    command: Sequence[str]
) -> subprocess.CompletedProcess:
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
    try:
        try_subprocess(intermediate_command)
        try_subprocess(final_command)
    except SubprocessError:
        raise
    else:
        os.remove(fpath_intermediate)

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


class PixelFormatter(object):
    def __init__(self):
        self._set_pixel_formats()

    def _set_pixel_formats(self):
        """ Runs ffmpeg to get all pix_fmts and creates a lookup for pix_fmt metadata
        """
        cmd = [
            "ffmpeg",
            "-loglevel", "panic",
            "-pix_fmts"
        ]
        lines = try_subprocess(cmd).stdout.strip().split("\n")
        for i, line in enumerate(lines):
            if line == "-----":
                break
        lines = lines[i + 1:]
        # permissible_in = [line for line in lines if line[0] == "I"]
        # permissible_out = [line for line in lines if line[1] == "O"]
        self.metadata_lookup = {}
        for line in lines:
            line_ = line.split()
            self.metadata_lookup[line_[1]] = {
                "flags": line_[0],
                "nb_components": int(line_[2]),
                "bits_per_pixel": int(line_[3]),
                "bit_depths": [int(x) for x in line_[4].split('-')],
            }

    def get_common_pix_fmt(
        self,
        pix_fmts: Sequence[str]
    ) -> str:
        """ Determines best possible (and easy-to-use) pix_fmt among all
            options, without attempting to upsample or anything
        """
        channel_fmt = 'yuv'
        bits_per_pixel = max([fmt['bits_per_pixel'] for fmt in self.metadata_lookup.values()])
        n_little_endian = 0
        n_big_endian = 0
        use_alpha = False
        bit_depth = bits_per_pixel

        for pix_fmt in pix_fmts:
            md = self.metadata_lookup[pix_fmt]

            # Minimum bits per pixel & bit depth
            bits_per_pixel = min(bits_per_pixel, md['bits_per_pixel'])
            bit_depth = min(bit_depth, max(md['bit_depths']))

            # Count little-endian
            if pix_fmt.endswith('le'):
                n_little_endian += 1

            # Count big-endian
            if pix_fmt.endswith('be'):
                n_big_endian += 1

            if len(md['bit_depths']) > 3:
                use_alpha = True

        # Start constructing the common pixel_format
        common_pix_fmt = channel_fmt

        # NOTE no support for alpha yet - it clashes with heuristic below
        if use_alpha and False:
            common_pix_fmt += "a"

        # Heuristic for determining chroma subsampling
        if bits_per_pixel / bit_depth >= 3:
            common_pix_fmt += "444p"
        elif bits_per_pixel / bit_depth >= 2:
            # NOTE this coerces 440 to 422
            common_pix_fmt += "422p"
        elif bits_per_pixel / bit_depth >= 1.5:
            common_pix_fmt += "420p"
        else:
            raise ValueError(f"cannot infer common pix_fmt from {pix_fmts}")

        # Bitdepth modifier
        if bit_depth > 8:
            common_pix_fmt += str(int(bit_depth))
            common_pix_fmt += "le" if n_little_endian >= n_big_endian else "be"

        return common_pix_fmt
