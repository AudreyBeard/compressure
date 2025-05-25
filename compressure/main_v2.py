import logging
import queue
import subprocess
import threading
from pathlib import Path
from typing import List

import mido

from compressure.compression import SingleVideoCompression
from compressure.midi import ParserDeque  # noqa
from compressure.stream import (
    Consumer,
    Producer,
)

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
        index: int
    ):
        self.index = index
        stream = self.controllers[index].selected_stream
        position = self.controllers[index].pos_current
        width = self.controllers[index].width
        return stream, position, width

    def navigate(
        self,
        position: float,
        width: float,
        index: int = -1,
    ):
        self.index = index if index >= 0 else self.index
        return self.controllers[index].navigate(position, width)


def main(
    fpath_in: str,
    midi_object_name: str = 'nanoKONTROL2 SLIDER/KNOB',
    width_max: float = 1.0,
):

    fpath_fwd, fpath_bak = import_reverse(
        fpath_in=fpath_in,
    )

    print("getting metadata")
    md = get_video_metadata(
        fpath_fwd
    )

    print("initializing navigator")
    navigator = NavigationController(
        fpath_fwd,
        fpath_bak,
    )

    chunk_q = queue.Queue(maxsize=500)

    print("initializing producer")
    producer = Producer(
        chunk_q,
        debug=True,
        repeat_chunks=False,
        repeat_chunks_for_sec=0.05,
    )

    print("initializing consumer")
    consumer = Consumer(
        fpath_video_init=fpath_fwd,
        chunk_q=chunk_q,
        width_init=0.5,
        debug=True,
    )

    print("starting consumer")
    threading.Thread(target=consumer._start, daemon=True).start()

    position = 0.0
    width = 0.5
    fpath_selected = fpath_fwd
    with mido.open_input(midi_object_name) as port:
        #port._queue = ParserDeque()
        print("opened midi port")
        producer.update(
            fpath_video=fpath_selected,
            position=position,
            width=width
        )
        print(port._queue)
        msg = None
        while True:
            #with port._lock:
            #    if port._messages:
            #        msg = port._messages.pop()
            #    else:
            #        msg = None
            #msg = port.poll()
            #msg_sample = port.poll()
            #while msg_sample is not None:
            #    msg_sample = port.poll()
            #    msg = msg_sample
            #if msg_old:
            msg = get_midi_message(port)
            if msg:
                position, width = update_position_width(
                    midi_msg=msg,
                    position_old=position,
                    width_old=width,
                    video_duration=md['duration'],
                    video_frames=md['frames']
                )

                fpath_selected, _, _ = navigator.navigate(position, width)
                position = md['duration'] - position if fpath_selected == fpath_bak else position
                print(fpath_selected, f"{position:.3f}", f"{width:.3f}")
                producer.update(
                    fpath_video=fpath_selected,
                    position=position,
                    width=width
                )


def update_position_width(
    midi_msg,
    position_old: float,
    width_old: float,
    video_duration: float,
    video_frames: int,
):
    position, width = position_old, width_old
    try:
        if midi_msg.control == 120:
            position = midi_msg.value / 127 * video_duration
        elif midi_msg.control == 16:
            width = midi_msg.value / (video_frames / video_duration)
    except AttributeError:
        pass

    return position, width


def get_midi_message(
    port,
):
    msg_sample = port.poll()
    msg = msg_sample
    while msg_sample is not None:
        msg = msg_sample
        msg_sample = port.poll()
    return msg


if __name__ == "__main__":
    logging.basicConfig(filename="main_v2.log", level=logging.INFO)
    main('input.mp4')
