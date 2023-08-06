from argparse import ArgumentParser
from collections import deque
from multiprocessing import Pool
import os
from pathlib import Path
from pprint import pformat

import ipdb  # noqa
import numpy as np
from tqdm import tqdm

from compressure.dataproc import VideoMetadata, try_subprocess, concat_videos
from compressure.persistence import (
    VideoCompressionPersistenceDefaults,
    VideoSlicerPersistenceDefaults,
)
from compressure.compression import VideoCompressionDefaults, VideoCompressionSystem
from compressure.exceptions import (
    EncoderSelectionError,
    MalformedConfigurationError,
    UnrecognizedEncoderConfigError,
)


class VideoSlicerDefaults(object):
    workdir = VideoSlicerPersistenceDefaults.workdir


class VideoSlicer(object):
    def __init__(self, fpath_in, superframe_size=6,
                 workdir=VideoSlicerDefaults.workdir,
                 ):
        self.fpath_in = fpath_in
        self.video_metadata = VideoMetadata(self.fpath_in)
        self.superframe_size = superframe_size
        self.slice_duration = self.superframe_size / self.video_metadata.fps
        self.workdir = str(Path(workdir))
        os.makedirs(self.workdir, exist_ok=True)

        self._init_start_times()
        self.slices = [str(Path(self.workdir) / f"slice_{i}.avi") for i in range(len(self.start_times))]

    def _init_start_times(self):
        self.start_times = np.arange(
            0,
            self.video_metadata.duration - self.superframe_size / self.video_metadata.fps,
            1 / self.video_metadata.fps
        )

    def slice_video(self, n_workers=0):
        if n_workers > 0:
            # TODO pick up here
            # NOTE this is experimental
            args_list = [
                (
                    self.fpath_in,
                    self.slices[i],
                    start_time,
                    self.slice_duration
                )
                for i, start_time in enumerate(self.start_times)
            ]
            # ipdb.set_trace()
            with Pool(n_workers) as p:
                p.starmap(
                    self.extract_single_slice,
                    tqdm(
                        args_list,
                        total=len(args_list),
                        desc=f"[slicing] superframe_size: {self.superframe_size}"
                    )
                )

        for i, start_time in tqdm(
            enumerate(self.start_times),
            total=len(self.start_times),
            desc=f"[slicing] superframe_size {self.superframe_size}"
        ):
            self.extract_single_slice(
                str(self.fpath_in),
                self.slices[i],
                start_time,
                self.slice_duration
            )

    def extract_single_slice(
        self,
        fpath_in: str,
        fpath_out: str,
        start_time: float,
        slice_duration: float,
    ):
        command = [
            "ffmpeg", "-y",
            "-v", "error",
            "-i", fpath_in,
            "-c", "copy",
            "-ss", f"{start_time:.3f}",
            "-t", f"{slice_duration:.3f}",
            "-copyinkf",
            fpath_out
        ]
        process = try_subprocess(command)
        return process

    @property
    def human_readable_string(self):
        s = ""
        s += f"superframe_size={self.superframe_size}"
        return s


class VideoCompressureValve(object):
    def __init__(self, fpath_in, superframe_size=6,
                 workdir=VideoCompressionPersistenceDefaults.workdir):
        self.slicer = VideoSlicer(
            fpath_in=fpath_in,
            superframe_size=superframe_size,
            workdir=workdir
        )
        self._velocity_numerator = superframe_size
        self._velocity_denominator = superframe_size

        self.slicer.slice_video()
        self.buffer = deque(self.slicer.slices)
        self.index = 0

    @property
    def workdir(self):
        return self.slicer.workdir

    @property
    def state(self):
        return self.buffer[0]

    @property
    def velocity(self):
        return self._velocity_numerator / self._velocity_denominator

    @velocity.setter
    def velocity(self, velocity):
        #self._velocity_numerator = velocity * self._velocity_denominator
        self._velocity_numerator = int(velocity * self.superframe_size)

    def step(self, to=None):
        if to is not None:
            n_moves = to - self.index
            if n_moves > 0:
                self.velocity = 1
            else:
                self.velocity = 0
        else:
            n_moves = int(self.superframe_size * self.velocity)
        return self._get_new_state(n_moves)

    def _get_new_state(self, n_moves):
        self.buffer.rotate(-n_moves)
        self.index += n_moves
        return self.state

    def accelerate(self, degree=0):
        self.velocity = self.velocity + degree / self.superframe_size
        return self.step()

    def __len__(self):
        return len(self.buffer)


class VideoCompressureValveReversible(object):
    def __init__(self, fpath_in_forward, fpath_in_backward, superframe_size=6,
                 workdir=VideoCompressionPersistenceDefaults.workdir):

        # First set working directory for forward and backwards motion, create if needed
        dpath_forward = Path(workdir) / "forward"
        dpath_backward = Path(workdir) / "backward"

        os.makedirs(dpath_forward, exist_ok=True)
        os.makedirs(dpath_backward, exist_ok=True)

        self.valve_forward = VideoCompressureValve(
            fpath_in_forward,
            superframe_size=6,
            workdir=Path(workdir) / "forward"
        )
        self.valve_backward = VideoCompressureValve(
            fpath_in_backward,
            superframe_size=6,
            workdir=Path(workdir) / "backward"
        )

        self._velocity = 1
        self._velocity_numerator = self.superframe_size
        self._velocity_denominator = self.superframe_size
        self.index = 0
        self.direction = 1

    @property
    def state(self):
        return self.valve_forward.state if self.direction > 0 else self.valve_backward.state

    @property
    def velocity(self):
        return self._velocity_numerator / self._velocity_denominator

    @velocity.setter
    def velocity(self, velocity):
        if self.direction > 0:
            self.direction = 1 if self.velocity >= 0 else -1
        else:
            self.direction = 1 if self.velocity > 0 else -1

        self._velocity_numerator = int(velocity * self._velocity_denominator)
        self.valve_forward.velocity = velocity
        self.valve_backward.velocity = velocity

    def step(self, to=None):
        if to is not None:
            n_moves = to - self.index
            if n_moves > 0:
                self.velocity = 1
            elif n_moves < 0:
                self.velocity = -1
            else:
                self.velocity = 0
        else:
            n_moves = int(self.superframe_size * self.velocity)

        self.valve_forward.step(to)
        self.valve_backward.step(to)
        return self.state

    def accelerate(self, degree=1):
        self.velocity = self.velocity + degree / self.superframe_size
        return self.step()

    def __len__(self):
        return len(self.valve_forward)


def construct_encoder_config(encoder, user_specified_config):
    try:
        encoder_config = VideoCompressionDefaults.encoder_config_options[encoder]
    except KeyError:
        raise EncoderSelectionError(encoder)

    for i in range(0, len(user_specified_config), 2):
        try:
            key = user_specified_config[i]
            value = user_specified_config[i + 1]
        except IndexError:
            raise MalformedConfigurationError(len(user_specified_config))

        if encoder_config.get(key) is None:
            # TODO this should just be a warning
            raise UnrecognizedEncoderConfigError(encoder, key)
        else:
            encoder_config[key] = value
    return encoder_config


def main():
    args = parse_args()
    # encoder_config = construct_encoder_config(args.encoder, args.encoder_config)
    compression = VideoCompressionSystem()
    fpath = compression.compress(
        args.fpath_in,
        gop_size=6000,
        encoder=args.encoder,
        encoder_config=args.encoder_config
    )
    valve = VideoCompressureValve(fpath, superframe_size=args.superframe_size)

    video_list = [valve.state]
    timeline = generate_timeline_function(
        args.superframe_size,
        len(valve),
        frequency=args.frequency,
        n_superframes=args.n_superframes - 1
    )

    for loc in timeline:
        video_list.append(valve.step(to=loc))

    print(f"Concatenating {len(video_list)} videos")
    concat_videos(video_list, fpath_out="output.avi")


def parse_args():
    parser = ArgumentParser()
    parser.add_argument(
        "--superframe-size",
        default=6,
        type=int,
        help="Number of frames per superframe unit"
    )
    parser.add_argument(
        "--fpath-in-forward",
        required=True,
        help="forward source video from which to sample"
    )
    parser.add_argument(
        "--fpath-in-backward",
        required=True,
        help="backward source video from which to sample"
    )
    parser.add_argument(
        "--i-frame-rate",
        default=6000,
        type=int,
        help="frequency of i-frames, translates to the -g option in ffmpeg"
    )
    parser.add_argument(
        "--destination",
        default="output.avi",
        help="location of output"
    )
    parser.add_argument(
        "--encoder",
        default=VideoCompressionDefaults.encoder,
        help=f"which encoder to use. \
            Must be one of {pformat(VideoCompressionDefaults.encoder_config_options.keys())}"
    )
    parser.add_argument(
        "--encoder-config",
        default="",
        nargs="+",
        help=f"""configuration, in form `key_0 value_0 key_1 value_1...`.
            If left unspecified, default values will be used for the following encoders:
            {pformat(VideoCompressionDefaults.encoder_config_options)}"""
    )
    parser.add_argument(
        "--frequency",
        default=0.5,
        type=float,
        help="frequency (wrt video length) of sinusoidal timeline"
    )
    parser.add_argument(
        "--n-superframes",
        default=400,
        type=int,
        help="how many superframes?"
    )
    return parser.parse_args()


def generate_timeline_function(superframe_size, len_lvb,
                               n_superframes=500, category="sinusoid",
                               frequency=1):
    if category == "sinusoid":
        locations = np.sin(
            np.linspace(0, 2 * np.pi * frequency, n_superframes)
        ) * (len_lvb - 1)
        locations[locations < 0] = -locations[locations < 0]
        return locations.astype(int)
    elif category == "compound-sinusoid":
        locations = np.sin(
            np.linspace(0, 2 * np.pi * frequency, n_superframes)
        ) * (len_lvb)
        locations[locations < 0] = -locations[locations < 0]
        return locations.astype(int)
    else:
        raise NotImplementedError(f"can't parse category {category} yet")


if __name__ == "__main__":
    main()
