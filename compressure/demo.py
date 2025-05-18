import logging
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import (
    List,
)

import numpy as np

from compressure.stream import Producer, Consumer
from compressure.compression import SingleVideoCompression

logger = logging.getLogger(__name__)


def generate_positions(
    video_length_sec: float,
    width_max: float = 0.5,
    n_chunks: int = 300,
    n_periods: float = 1,
):
    """
    """
    # First initialize from [0, 1]
    positions = -np.cos(
        np.linspace(0, 2 * np.pi * n_periods, n_chunks)
    ) / 2 + 0.5

    # Now scale it from [0, latest_allowable_time]
    positions *= video_length_sec - width_max
    return positions


def generate_widths(
    video_framerate_hz: float,
    n_chunks: int = 300,
    chunksize_frames_min: int = 3,
    chunksize_frames_max: int = 30,
    n_periods: float = 1,
):
    """
    """
    # First initialize from [0, 1]
    widths = -np.cos(
        np.linspace(0, 2 * np.pi * n_periods, n_chunks)
    ) / 2 + 0.5

    # Now scale between min and max width
    widths *= (chunksize_frames_max - chunksize_frames_min)
    widths += chunksize_frames_min
    return widths / video_framerate_hz


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


def main(
    fpath_video: str,
    n_chunks: int = 300,
    chunksize_frames_min: int = 6,
    chunksize_frames_max: int = 60,
    n_periods_width: int = 1,
    n_periods_position: int = 0.5,
    producer_repeat_chunks: bool = False,
    producer_repeat_chunks_for_sec: float = 0.5,
    debug: bool = False,
):
    logging.basicConfig(filename="demo.log", level=logging.INFO)
    logger.info("Getting metadata")
    metadata = get_video_metadata(fpath_video)

    logger.info("Generating widths")
    widths = generate_widths(
        metadata['frames'] / metadata['duration'],
        n_chunks=n_chunks,
        chunksize_frames_min=chunksize_frames_min,
        chunksize_frames_max=chunksize_frames_max,
        n_periods=n_periods_width,
    )
    logger.debug(f"widths: {widths}")

    logger.info("Generating positions")
    positions = generate_positions(
        metadata['duration'],
        widths.max(),
        n_chunks=n_chunks,
        n_periods=n_periods_position,
    )
    logger.debug(f"positions: {positions}")

    logger.info("Initializing queue")
    chunk_queue = queue.Queue(maxsize=500)

    logger.info("Initializing producer")
    producer = Producer(
        chunk_queue,
        debug=debug,
        repeat_chunks=producer_repeat_chunks,
        repeat_chunks_for_sec=producer_repeat_chunks_for_sec,
    )

    logger.info("Initializing consumer")
    consumer = Consumer(
        fpath_video_init=fpath_video,
        chunk_q=chunk_queue,
        width_init=0.5,
        debug=debug,
    )

    logger.info("Starting consumer")
    threading.Thread(target=consumer._start, daemon=True).start()
    #consumer.start()

    logger.info("Starting navigation")
    time.sleep(1)
    for position, width in zip(positions, widths):
        producer.update(
            fpath_video=fpath_video,
            position=position,
            width=width,
        )

    logger.info("Done")


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


def import_and_process(
    fpath_in: str,
    qp: int = -1,
    preset: str = "ultrafast",
    gop_size: int = 6000,
    n_chunks: int = 300,
    chunksize_frames_min: int = 6,
    chunksize_frames_max: int = 60,
    n_periods_width: int = 1,
    n_periods_position: int = 2,
    producer_repeat_chunks: bool = True,
    producer_repeat_chunks_for_sec: float = 0.1,
    debug: bool = False,
):
    fpath_compressed, fpath_compressed_reverse = import_reverse(
        fpath_in,
        qp=qp,
        preset=preset,
        gop_size=gop_size,
    )
    logging.basicConfig(filename="demo.log", level=logging.INFO)
    logger.info("Getting metadata")
    metadata = get_video_metadata(fpath_compressed)

    logger.info("Generating widths")
    widths = generate_widths(
        metadata['frames'] / metadata['duration'],
        n_chunks=n_chunks,
        chunksize_frames_min=chunksize_frames_min,
        chunksize_frames_max=chunksize_frames_max,
        n_periods=n_periods_width,
    )
    logger.debug(f"widths: {widths}")

    logger.info("Generating positions")
    positions = generate_positions(
        metadata['duration'],
        widths.max(),
        n_chunks=n_chunks,
        n_periods=n_periods_position,
    )
    print(positions)
    logger.debug(f"positions: {positions}")

    logger.info("Initializing queue")
    chunk_queue = queue.Queue(maxsize=500)

    logger.info("Initializing producer")
    producer = Producer(
        chunk_queue,
        debug=debug,
        repeat_chunks=producer_repeat_chunks,
        repeat_chunks_for_sec=producer_repeat_chunks_for_sec,
    )

    logger.info("Initializing consumer")
    consumer = Consumer(
        fpath_video_init=fpath_compressed,
        chunk_q=chunk_queue,
        width_init=0.5,
        debug=debug,
    )

    logger.info("Initializing navigator")
    navigator = NavigationController(
        fpath_fwd=fpath_compressed,
        fpath_bak=fpath_compressed_reverse
    )

    logger.info("Starting consumer")
    threading.Thread(target=consumer._start, daemon=True).start()
    #consumer.start()

    logger.info("Starting navigation")
    time.sleep(1)
    for position, width in zip(positions, widths):
        fpath_selected = navigator.select_stream(position)
        producer.update(
            fpath_video=fpath_selected,
            position=position,
            width=width,
        )

    logger.info("Done")
    return


class NavigationController(object):
    def __init__(
        self,
        fpath_fwd: str,
        fpath_bak: str,
    ):
        self.fpath_fwd = fpath_fwd
        self.fpath_bak = fpath_bak
        self.pos_current = 0
        self.width = 0.5
        self.selected_stream = fpath_fwd

    def navigate(
        self,
        pos_new: float,
        width: float,
    ):
        if pos_new < self.pos_current:
            self.selected_stream = self.fpath_bak
        elif pos_new > self.pos_current:
            self.selected_stream = self.fpath_fwd

        self.pos_current = pos_new
        self.width = width
        return self.selected_stream, self.pos_current, self.width


class MultiNavigationController(object):
    def __init__(
        self,
        fpaths_fwd: List[str],
        fpaths_bak: List[str],
    ):
        self.index = 0
        self.fpaths_fwd = fpaths_fwd
        self.fpaths_bak = fpaths_bak
        self.controllers = []
        for i, (fp_fwd, fp_bak) in enumerate(fpaths_fwd, fpaths_bak):
            self.controllers.append(NavigationController(
                fp_fwd,
                fp_bak
            ))

    def select_channel(
        self,
        index
    ):
        self.index = index
        stream = self.controllers[index].selected_stream
        position = self.controllers[index].pos_current
        width = self.controllers[index].width
        return stream, position, width

    def navigate(
        self,
        index,
        position,
        width,
    ):
        self.index = index
        return self.controllers[index].navigate(position, width)


if __name__ == "__main__":
    main('input.mp4')
