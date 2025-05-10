import logging
import queue
import subprocess
import threading
import time

import numpy as np

from compressure.stream import Producer, Consumer

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


if __name__ == "__main__":
    main('input.mp4')
