import logging
from pathlib import Path
import subprocess

from compressure.compression import SingleVideoCompression

logger = logging.getLogger(__name__)


def get_video_length(
    fpath: str,
) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        fpath
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        raise ValueError(e.stderr.decode().strip())
    try:
        result_float = float(result.stdout)
    except ValueError as e:
        raise e
    else:
        return result_float


def get_video_frames(
    fpath: str,
) -> int:
    """ Counts number of packets / frames. This takes a moment.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-count_packets",
        "-show_entries", "stream=nb_read_packets",
        "-of", "default=noprint_wrappers=1:nokey=1",
        fpath
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    try:
        result_int = float(result.stdout)
    except ValueError as e:
        raise e
    else:
        return result_int


def get_video_metadata(
    fpath_video: str,
):
    metadata = {
        "duration": get_video_length(fpath_video),
        "frames": get_video_frames(fpath_video),
    }
    return metadata


def reverse_video(
    fpath_in: str,
    fpath_out: str,
    qp: int = -1,
    preset: str = "ultrafast",
):
    cmd = [
        "ffmpeg", "-y",
        "-loglevel", "error",
        "-i", fpath_in,
        "-c:v", "libx264",
        "-qp", str(qp),
        "-preset", preset,
        "-vf", "reverse",
        fpath_out,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.info(f"[ffmpeg error] {e.stderr.decode().strip()}")
        raise ValueError(e.stderr.decode().strip())


def import_reverse(
    fpath_in: str,
    qp: int = -1,
    preset: str = "ultrafast",
    gop_size: int = 6000,
):
    fpath_in_ = Path(fpath_in).expanduser().absolute()
    fpath_reverse_ = fpath_in_.with_stem(fpath_in_.stem + "_reverse").with_suffix(".mp4")

    print("Reversing original video")
    reverse_video(
        fpath_in=str(fpath_in_),
        fpath_out=str(fpath_reverse_),
        qp=qp,
        preset=preset,
    )

    compressor = SingleVideoCompression(
        fpath_in=str(fpath_in_),
        workdir=str(Path('.').absolute()),
        gop_size=gop_size,
        encoder='libx264',
        encoder_config={
            'qp': qp,
            'preset': preset
        },
    )
    print("Compressing input")
    fpath_out, _ = compressor.transcode_video()

    compressor = SingleVideoCompression(
        fpath_in=str(fpath_reverse_),
        workdir=str(Path('.').absolute()),
        gop_size=gop_size,
        encoder='libx264',
        encoder_config={
            'qp': qp,
            'preset': preset
        },
    )

    print("Compressing reversed")
    fpath_out_reverse, _ = compressor.transcode_video()
    return fpath_out, fpath_out_reverse
