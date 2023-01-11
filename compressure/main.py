import os
from copy import deepcopy
from collections import deque
import logging
from argparse import ArgumentParser
from pprint import pformat
from pathlib import Path

import ipdb  # noqa
import numpy as np

from compressure.file_interface import nicely_sorted
from compressure.compression import SingleVideoCompression, VideoCompressionDefaults
from compressure.persistence import CompressurePersistence
from compressure.valve import VideoSlicer
from compressure.dataproc import concat_videos, reverse_loop
from compressure.exceptions import (
    EncoderSelectionError,
    MalformedConfigurationError,
    UnrecognizedEncoderConfigError,
)


class CompressureSystem(object):
    def __init__(self, fpath_manifest=CompressurePersistence.defaults.fpath_manifest,
                 workdir=CompressurePersistence.defaults.workdir,
                 verbosity=1):

        self.persistence = CompressurePersistence(
            fpath_manifest=fpath_manifest,
            workdir=workdir,
            verbosity=verbosity
        )

        self.verbosity = verbosity

    def pre_reverse(self, fpath_in):
        fpath_reverse_loop = reverse_loop(fpath_in)
        return fpath_reverse_loop

    def compress(self,
                 fpath_in: str,
                 gop_size: int = 6000,
                 encoder: str = VideoCompressionDefaults.encoder,
                 encoder_config: dict = {},
                 workdir: str = VideoCompressionDefaults.workdir,
                 ) -> str:
        """ Encodes video file with specified parameters
            Parameters:
                - fpath_in: video file path
                - gop_size: group of pictures size (number of p-frames per i-frame)
                - encoder: codec name, see VideoCompressionDefaults
                - encoder_config: codec parameters, see VideoCompressionDefaults and ffmpeg docs
                - workdir: location for encoded files
            Returns:
                - string filepath to encoded video
        """

        compressor = SingleVideoCompression(
            fpath_in=fpath_in,
            workdir=workdir,
            gop_size=gop_size,
            encoder=encoder,
            encoder_config=encoder_config
        )
        try:
            # First see if we've already encoded it
            encode = self.persistence.get_encode(
                fpath_source=fpath_in,
                fpath_encode=compressor.fpath_out,
            )
        except KeyError:
            self._log_print(
                "No video found in persistent storage - creating now",
                logging.info
            )
            # If we haven't encoded, do that now
            fpath_out, _ = compressor.transcode_video()

            # Add encoding to manifest and get entry back
            encode = self.persistence.add_encode(
                fpath_source=fpath_in,
                fpath_encode=fpath_out,
                parameters=compressor.encoder_config_dict,
                command=compressor.transcode_command
            )
            self._log_print(
                f"Successfully added & transcoded video to {fpath_out}",
                logging.info
            )

        # Return filepath for later use
        return encode['fpath']

    def remove_encode(self, fpath_source: str, fpath_encode: str) -> None:
        self.persistence.remove_encode(fpath_source, fpath_encode)

    def _log_print(self, msg, log_op):
        if self.verbosity > 0:
            print(msg)

        log_op(msg)

    def slice(self, fpath_source: str, fpath_encode: str, superframe_size: int = 6) -> str:
        """ Slices encoded video into short chunks, writing all to a location
            defined by the persistence class.
            NOTE that this method will create `ceil(n_frames(original) / superframe_size)`
            video files, each `superframe_size` frames long.
            Parameters:
                - fpath_source: source path, used only for indexing into persistence object
                - fpath_encode: encode path, the input file for slicing
                - superframe_size: number of frames per slice.
            Returns:
                string directory path to slices
        """
        try:
            slices = self.persistence.get_slices(fpath_source, fpath_encode, superframe_size)
        except KeyError:
            ipdb.set_trace()
            workdir = self.persistence.init_slices_dir(fpath_encode, superframe_size)

            slicer = VideoSlicer(
                fpath_in=fpath_encode,
                superframe_size=superframe_size,
                workdir=workdir
            )
            slicer.slice_video()
            slices = self.persistence.add_slices(fpath_source, fpath_encode, superframe_size)

        return slices

    def init_buffer(self,
                    dpath_slices_forward: str,
                    dpath_slices_backward: str,
                    superframe_size: int,
                    ) -> "VideoSliceBufferReversible":
        """ Initializes video buffer for forward/reverse traversal
        """
        buffer = VideoSliceBufferReversible(
            dpath_slices_forward,
            dpath_slices_backward,
            superframe_size
        )
        return buffer


# TODO work on this
class VideoSliceBufferReversible(object):
    def __init__(self, dpath_slices_forward: str, dpath_slices_backward: str, superframe_size: int):

        # TODO buffer needs parent directories for
        slices_forward = nicely_sorted([
            str(Path(dpath_slices_forward) / fname)
            for fname in os.listdir(dpath_slices_forward)
        ])
        slices_backward = nicely_sorted([
            str(Path(dpath_slices_backward) / fname)
            for fname in os.listdir(dpath_slices_backward)
        ])

        self.buffer_forward = deque(slices_forward)
        self.buffer_backward = deque(slices_backward[::-1])

        self.forward = True
        self.index = 0

        self._velocity_numerator = superframe_size
        self._velocity_denominator = superframe_size

    @property
    def state(self):
        return self.buffer_forward[0] if self.forward else self.buffer_backward[0]

    @property
    def velocity(self):
        return self._velocity_numerator / self._velocity_denominator

    @velocity.setter
    def velocity(self, velocity):
        self.forward = self.velocity >= 0 if self.forward else self.velocity > 0

        self._velocity_numerator = int(velocity * self._velocity_denominator)

    def step(self, to=None):
        """ Steps to the "next" state, determined by the superframe size and velocity.
        """
        if to is not None:
            n_moves = to - self.index
            # self.velocity = 1 if n_moves >= 0 else -1
            if n_moves < 0:
                self.velocity = -1
            elif n_moves > 0:
                self.velocity = 1
            else:
                self.velocity = 0
        else:
            n_moves = int(self.superframe_size * self.velocity)

        self.buffer_forward.rotate(-n_moves)
        self.buffer_backward.rotate(-n_moves)

        # Subtle differences designed to maintain temporal stability in case of
        # zero-velocity within monotonic steps
        # if self.forward:
        #     self.state = self.buffer_forward[0] if self.velocity >= 0 else self.buffer_backward[0]
        # else:
        #     self.state = self.buffer_forward[0] if self.velocity > 0 else self.buffer_backward[0]

        self.index += n_moves
        if self.forward:
            state = self.buffer_forward[0] if self.velocity >= 0 else self.buffer_backward[0]
        else:
            state = self.buffer_forward[0] if self.velocity > 0 else self.buffer_backward[0]
        return state

    def accelerate(self, degree=1):
        """ Changes velocity
        """
        self.velocity = self.velocity + degree / self.superframe_size
        return self.step()

    def __len__(self):
        return len(self.buffer_forward)


def generate_timeline_function(superframe_size, len_lvb,
                               n_superframes=500, category="sinusoid",
                               frequency=1, scaled=False, rectified=True):
    if category == "sinusoid":
        if scaled and rectified:
            raise ValueError("either scaled or rectified must be False")

        locations = -np.cos(
            np.linspace(0, 2 * np.pi * frequency, n_superframes)
        )
        if rectified:
            locations[locations < 0] = -locations[locations < 0]
            locations = locations * (len_lvb - 1)
        elif scaled:
            locations = (locations - locations.min()) / (locations.max() - locations.min())
            locations = locations * (len_lvb - 2) + 1

        return locations.astype(int)

    elif category == "compound-sinusoid":
        locations = np.sin(
            np.linspace(0, 2 * np.pi * frequency, n_superframes)
        ) * (len_lvb)
        locations[locations < 0] = -locations[locations < 0]
        return locations.astype(int)
    else:
        raise NotImplementedError(f"can't parse category {category} yet")


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


def parse_args():
    parser = ArgumentParser()
    parser.add_argument(
        "--pre_reverse_loop",
        action="store_true",
        help="Reverse loop the videos before processing?"
    )
    parser.add_argument(
        "--superframe_size",
        default=6,
        type=int,
        help="Number of frames per superframe unit"
    )
    parser.add_argument(
        '-f', "--fpath_in_forward",
        required=True,
        help="forward source video from which to sample"
    )
    parser.add_argument(
        '-b', "--fpath_in_backward",
        required=True,
        help="backward source video from which to sample"
    )
    parser.add_argument(
        "--frequency",
        default=0.5,
        type=float,
        help="frequency (wrt video length) of sinusoidal timeline"
    )
    parser.add_argument(
        "--n_superframes",
        default=400,
        type=int,
        help="how many superframes?"
    )
    parser.add_argument(
        '--scaled',
        action="store_true",
        help="should we scale the timeline such that it's never negative? mutually exclusive with --rectified"
    )
    parser.add_argument(
        '--rectified',
        action="store_true",
        help="should we rectify the timeline such that it's never negative? mutually exclusive with --scaled"
    )
    parser.add_argument(
        "-o", "--fpath_out",
        default="output.avi",
        help="Output filepath. Should have '.avi' extension in most circumstances."
    )
    parser.add_argument(
        "-g", "--gop_size",
        default=VideoCompressionDefaults.gop_size,
        help="Group of pictures (gop) size, or inverse frequency of IDR frames."
    )
    parser.add_argument(
        "--encoder",
        default=VideoCompressionDefaults.encoder,
        help=f"which encoder to use. \
            Must be one of {pformat(VideoCompressionDefaults.encoder_config_options.keys())}"
    )
    parser.add_argument(
        "--encoder_config",
        default="",
        nargs="+",
        help=f"""configuration, in form `key_0 value_0 key_1 value_1...`.
            If left unspecified, default values will be used for the following encoders:
            {pformat(VideoCompressionDefaults.encoder_config_options)}"""
    )
    args = parser.parse_args()
    assert args.scaled or args.rectified
    return args


def main():
    args = parse_args()
    controller = CompressureSystem()
    encoder_config = construct_encoder_config(args.encoder, args.encoder_config)
    if args.pre_reverse_loop:
        raise NotImplementedError("reverse-looping needs work. don't use it")
        print("reverse-looping input")
        fpath_in_forward = reverse_loop(args.fpath_in_forward)
        fpath_in_backward = reverse_loop(args.fpath_in_backward)
    else:
        fpath_in_forward = args.fpath_in_forward
        fpath_in_backward = args.fpath_in_backward

    fpath_encode_forward = controller.compress(
        fpath_in_forward,
        gop_size=args.gop_size,
        encoder=args.encoder,
        encoder_config=encoder_config
    )
    dpath_slices_forward = controller.slice(
        fpath_source=fpath_in_forward,
        fpath_encode=fpath_encode_forward,
        superframe_size=args.superframe_size
    )

    if fpath_in_backward:
        fpath_encode_backward = controller.compress(
            fpath_in_backward,
            gop_size=args.gop_size,
            encoder=args.encoder,
            encoder_config=encoder_config
        )
        dpath_slices_backward = controller.slice(
            fpath_source=fpath_in_backward,
            fpath_encode=fpath_encode_backward,
            superframe_size=args.superframe_size
        )

    buffer = controller.init_buffer(dpath_slices_forward, dpath_slices_backward, args.superframe_size)

    # TODO pick up here
    initial_state = deepcopy(buffer.state)
    timeline = generate_timeline_function(
        args.superframe_size,
        len(buffer),
        frequency=args.frequency,
        n_superframes=args.n_superframes - 1,
        scaled=args.scaled,
        rectified=args.rectified
    )

    if timeline[0] == initial_state:
        video_list = []
    else:
        video_list = [initial_state]

    for loc in timeline:
        video_list.append(buffer.step(to=loc))

    print(f"Concatenating {len(video_list)} videos")
    concat_videos(video_list, fpath_out=args.fpath_out)
    print(args.fpath_out)


if __name__ == "__main__":
    with ipdb.launch_ipdb_on_exception():
        main()
