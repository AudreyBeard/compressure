import cProfile
import logging
import queue
import subprocess
import threading
from pathlib import Path
from typing import (
    List,
    Tuple,
)

import mido
from tqdm import tqdm

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


def extract_clip(
    fpath_in: str,
    t_start: float,
    t_end: float,
    fpath_out: str,
):
    cmd = [
        "ffmpeg", "-y",
        "-copyts",
        "-ss", f"{t_start:.3f}",
        "-i", fpath_in,
        "-to", f"{t_end:.3f}",
        "-map", "0",
        "-c", "copy",
        fpath_out,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.info(f"[ffmpeg error] {e.stderr.decode().strip()}")
        raise ValueError(e.stderr.decode().strip())


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
    workdir: str = "~/.cache/compressure",
):
    fpath_in_ = Path(fpath_in).expanduser().absolute()
    fpath_reverse_ = fpath_in_.with_stem(fpath_in_.stem + "_reverse").with_suffix(".mp4")

    #print("Reversing original video")
    reverse_video(
        fpath_in=str(fpath_in_),
        fpath_out=str(fpath_reverse_),
        qp=qp,
        preset=preset,
    )

    compressor = SingleVideoCompression(
        fpath_in=str(fpath_in_),
        workdir=str(Path(workdir).expanduser().absolute()),
        gop_size=gop_size,
        encoder='libx264',
        encoder_config={
            'qp': qp,
            'preset': preset
        },
    )
    #print("Compressing input")
    fpath_out, _ = compressor.transcode_video()

    compressor = SingleVideoCompression(
        fpath_in=str(fpath_reverse_),
        workdir=str(Path(workdir).expanduser().absolute()),
        gop_size=gop_size,
        encoder='libx264',
        encoder_config={
            'qp': qp,
            'preset': preset
        },
    )

    #print("Compressing reversed")
    fpath_out_reverse, _ = compressor.transcode_video()
    return fpath_out, fpath_out_reverse


class PositionNavigationController(object):
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


class VelocityNavigationController(object):
    def __init__(
        self,
        fpath: str,
        video_duration: float,
    ):
        self.fpath = fpath
        self.velolcity = 1
        self.width = 1.0 / 3.0
        self.position = 0
        self.duration = video_duration

    def navigate(
        self,
        velocity: float,
        width: float,
    ):
        stride = velocity * width
        self.position = (self.position + stride) % self.duration
        self.width = width
        self.velocity = velocity
        return self.fpath, self.position, self.width


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
        for i, (fp_fwd, fp_bak) in enumerate(zip(fpaths_fwd, fpaths_bak)):
            self.controllers.append(PositionNavigationController(
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
        self.index = index if index is not None and index >= 0 else self.index
        return self.controllers[index].navigate(position, width)


def import_chop_video(
    fpath_in: str,
    n_pieces: int = 8,
    qp: int = -1,
    preset: str = "ultrafast",
    gop_size: int = 6000,
    workdir: str = "~/.cache/compressure",
) -> Tuple[List[str], List[str]]:
    fpath_in_ = Path(fpath_in).expanduser().absolute()
    md = get_video_metadata(str(fpath_in_))

    fpaths_out = [None for i in range(n_pieces)]
    fpaths_out_rev = [None for i in range(n_pieces)]

    for i in tqdm(range(n_pieces), desc="Splitting & processing input video"):
        t_start = i * md['duration'] / n_pieces
        t_end = (i + 1) * md['duration'] / n_pieces
        fname_out = fpath_in_.stem + str(i) + ".avi"
        fpath_out = Path(workdir).expanduser().absolute() / fname_out
        extract_clip(
            str(fpath_in_),
            t_start,
            t_end,
            str(fpath_out)
        )
        fpaths_out[i], fpaths_out_rev[i] = import_reverse(
            str(fpath_out)
        )

    return fpaths_out, fpaths_out_rev


def main(
    fpath_in: str,
    midi_object_name: str = 'nanoKONTROL2 SLIDER/KNOB',
    width_max: float = 1.0,
    split_clip: bool = False,
    navigation_mode: str = "position",
):

    # TODO finish up the split clip functionality
    if split_clip:
        fpaths_fwd, fpaths_bak = import_chop_video(
            fpath_in=fpath_in,
        )
        fpath_fwd = fpaths_fwd[0]
        fpath_bak = fpaths_bak[0]
    else:
        fpath_fwd, fpath_bak = import_reverse(
            fpath_in=fpath_in,
        )

    print("getting metadata", flush=True)
    md = get_video_metadata(
        fpath_fwd
    )

    print("initializing navigator", flush=True)
    if split_clip:
        navigator = MultiNavigationController(
            fpaths_fwd,
            fpaths_bak,
        )
    else:
        if navigation_mode.lower() == "position":
            navigator = PositionNavigationController(
                fpath_fwd,
                fpath_bak,
            )
        else:
            navigator = VelocityNavigationController(
                fpath_fwd,
                video_duration=md['duration'],
            )

    chunk_q = queue.Queue(maxsize=500)

    print("initializing producer", flush=True)
    producer = Producer(
        chunk_q,
        debug=True,
        repeat_chunks=False,
        repeat_chunks_for_sec=0.05,
    )

    print("initializing consumer", flush=True)
    consumer = Consumer(
        fpath_video_init=fpath_fwd,
        chunk_q=chunk_q,
        width_init=0.5,
        debug=True,
    )

    print("starting consumer", flush=True)
    threading.Thread(target=consumer._start, daemon=True).start()

    # Ignored if navigation_mode == "position"
    velocity = 1.0

    position = 0.0
    width = 0.5
    index = 0
    fpath_selected = fpath_fwd
    with mido.open_input(midi_object_name) as port:
        interpreter = MidiInterpreter(port)
        #port._queue = ParserDeque()
        print("opened midi port", flush=True)
        producer.update(
            fpath_video=fpath_selected,
            position=position,
            width=width
        )
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
            msg = interpreter.get_message()
            if msg and navigation_mode.lower() == "position":
                if msg.control == 64:
                    position = 0
                    fpath_selected = fpath_fwd
                    navigator.selected_stream = fpath_selected
                    navigator.pos_current = position

                # TODO change this to speed control, not position
                position, width, index = interpreter.update_position_width_index(
                    midi_msg=msg,
                    position_old=position,
                    width_old=width,
                    index_old=index,
                    video_duration=md['duration'],
                    video_frames=md['frames']
                )

                if split_clip:
                    fpath_selected, _, _ = navigator.navigate(position, width, index)
                    position = md['duration'] - position if fpath_selected in fpaths_bak else position
                else:
                    fpath_selected, _, _ = navigator.navigate(position, width)
                    position = md['duration'] - position if fpath_selected == fpath_bak else position

            else:
                if msg and msg.control == 64:
                    position = 0
                    fpath_selected = fpath_fwd
                    navigator.selected_stream = fpath_selected
                    navigator.pos_current = position

                try:
                    velocity, width, index = interpreter.update_velocity_width_index(
                        midi_msg=msg,
                        velocity_old=velocity,
                        width_old=width,
                        index_old=index,
                        video_duration=md['duration'],
                        video_frames=md['frames']
                    )
                except AttributeError:
                    pass

                if split_clip:
                    fpath_selected, position, _ = navigator.navigate(velocity, width, index)
                    position = md['duration'] - position if fpath_selected in fpaths_bak else position
                else:
                    fpath_selected, position, _ = navigator.navigate(velocity, width)
                    position = md['duration'] - position if fpath_selected == fpath_bak else position

                print(fpath_selected, f"{position:.3f}", f"{width:.3f}")
                producer.update(
                    fpath_video=fpath_selected,
                    position=position,
                    width=width
                )


def update_position_width_index(
    midi_msg,
    position_old: float,
    width_old: float,
    index_old: int,
    video_duration: float,
    video_frames: int,
):
    def is_position(cc):
        return cc >= 120 and cc <= 127

    def is_width(cc):
        return cc >= 16 and cc <= 23

    def get_index(cc):
        if is_position(cc):
            return cc % 120
        elif is_width(cc):
            return cc % 16
        else:
            return cc % 64

    position, width, index = position_old, width_old, index_old
    try:
        if is_position(midi_msg.control):
            position = midi_msg.value / 127 * video_duration
        elif is_width(midi_msg.control):
            width = midi_msg.value / (video_frames / video_duration)
    except AttributeError:
        pass

    index = get_index(midi_msg.control)

    return position, width, index


def get_midi_message(
    port,
):
    """ This is a hacky and inefficient way to get and deliver only the most
        recent message in the queue
    """
    msg_sample = port.poll()
    msg = msg_sample
    while msg_sample is not None:
        msg = msg_sample
        msg_sample = port.poll()
    return msg


class MidiInterpreter(object):
    def __init__(
        self,
        port,
        verbosity: int = 2,
    ):
        self.port = port
        self._v = verbosity
        if self._v > 0:
            print(f"MIDI Port Queue: {self.port._queue}", flush=True)

    def get_message(
        self,
    ):
        """ This is a hacky and inefficient way to get and deliver only the most
            recent message in the queue
        """
        msg_sample = self.port.poll()
        msg = msg_sample
        while msg_sample is not None:
            msg = msg_sample
            msg_sample = self.port.poll()
        return msg

    def _cc_is_position(self, cc) -> bool:
        return cc >= 120 and cc <= 127

    def _cc_is_width(self, cc) -> bool:
        return cc >= 16 and cc <= 23

    def _get_index(self, cc) -> bool:
        if self._cc_is_position(cc):
            return cc % 120
        elif self._cc_is_width(cc):
            return cc % 16
        else:
            return cc % 64

    def update_position_width_index(
        self,
        midi_msg,
        position_old: float,
        width_old: float,
        index_old: int,
        video_duration: float,
        video_frames: int,
    ) -> Tuple[float, float, int]:
        """ Assumes:
            - NanoKontrol 2
            - position-based faders
            - width-based pots
        """
        position, width, index = position_old, width_old, index_old
        try:
            if self._cc_is_position(midi_msg.control):
                position = midi_msg.value / 127 * video_duration
            elif self._cc_is_width(midi_msg.control):
                width = midi_msg.value / (video_frames / video_duration)
        except AttributeError:
            pass

        index = self._get_index(midi_msg.control)

        return position, width, index

    def update_velocity_width_index(
        self,
        midi_msg,
        velocity_old: float,
        width_old: float,
        index_old: int,
        video_duration: float,
        video_frames: int,
    ) -> Tuple[float, float, int]:
        """ Assumes:
            - NanoKontrol 2
            - velocity-based faders
            - width-based pots
        """
        velocity, width, index = velocity_old, width_old, index_old
        try:
            if self._cc_is_position(midi_msg.control):
                velocity = midi_msg.value / 127
            elif self._cc_is_width(midi_msg.control):
                width = midi_msg.value / (video_frames / video_duration)
        except AttributeError:
            pass

        index = self._get_index(midi_msg.control)

        return velocity, width, index


def profile(
):
    cProfile.run('from compressure.main_v2 import main; main("input.mp4")')


if __name__ == "__main__":
    logging.basicConfig(filename="main_v2.log", level=logging.INFO)
    main('input.mp4', navigation_mode="velocity")
