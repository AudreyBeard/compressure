import os
from copy import deepcopy
from collections import deque
import logging
from argparse import ArgumentParser
from pprint import pformat
from pathlib import Path
from typing import Sequence, Union, Optional

import ipdb  # noqa
import numpy as np

from compressure.file_interface import nicely_sorted
from compressure.compression import SingleVideoCompression, VideoCompressionDefaults
from compressure.persistence import CompressurePersistence
from compressure.slicing import VideoSlicer
from compressure.dataproc import concat_videos, reverse_loop, VideoMetadata, PixelFormatter
from compressure.exceptions import (
    EncoderSelectionError,
    MalformedConfigurationError,
    UnrecognizedEncoderConfigError,
)


# String representign path and actual pathlike objects
MaybePathLike = Union[os.PathLike, str]


class CompressureSystem(object):
    def __init__(
        self,
        fpath_manifest: MaybePathLike = CompressurePersistence.defaults.fpath_manifest,
        workdir: MaybePathLike = CompressurePersistence.defaults.workdir,
        verbosity: int = 1
    ):

        self.persistence = CompressurePersistence(
            fpath_manifest=fpath_manifest,
            workdir=workdir,
            verbosity=verbosity
        )

        self.verbosity = verbosity

    def pre_reverse(self, fpath_in):
        fpath_reverse_loop = reverse_loop(fpath_in)
        return fpath_reverse_loop

    def compress(
        self,
        fpath_in: str,
        gop_size: int = 6000,
        encoder: str = VideoCompressionDefaults.encoder,
        encoder_config: Optional[dict] = None,
        workdir: str = None,
        fps: Optional[Sequence[int]] = None,
        pix_fmt: Optional[str] = None
    ) -> str:
        """ Encodes video file with specified parameters
            Parameters:
                - fpath_in: video file path
                - gop_size: group of pictures size (number of p-frames per i-frame)
                - encoder: codec name, see VideoCompressionDefaults
                - encoder_config: codec parameters, see VideoCompressionDefaults and ffmpeg docs
                - workdir: location for encoded files
                - fps: coerced framerate (sped up or slowed down), (-1, -1) for default
                - pix_fmt: coerced pixel format
            Returns:
                - string filepath to encoded video
        """

        workdir = workdir if workdir is not None else self.persistence.workdir

        encoder_config = {} if encoder_config is None else encoder_config
        compressor = SingleVideoCompression(
            fpath_in=fpath_in,
            workdir=workdir,
            gop_size=gop_size,
            encoder=encoder,
            encoder_config=encoder_config,
            fps=fps,
            pix_fmt=pix_fmt
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

    def slice(
        self,
        fpath_source: str,
        fpath_encode: str,
        superframe_size: int = 6,
        n_workers: int = 0,
    ) -> str:
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
            workdir = self.persistence.init_slices_dir(fpath_encode, superframe_size)

            slicer = VideoSlicer(
                fpath_in=fpath_encode,
                superframe_size=superframe_size,
                workdir=workdir
            )
            slicer.slice_video(n_workers=n_workers)
            slices = self.persistence.add_slices(fpath_source, fpath_encode, superframe_size)

            self.persistence.save()
            self.persistence = CompressurePersistence(
                fpath_manifest=self.persistence.manifest.fpath,
                workdir=self.persistence.workdir,
                verbosity=self.persistence.verbosity
            )
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


def parse_args(ignore_requirements=False):
    parser = ArgumentParser()
    parser.add_argument(
        "ffmpeg-report",
        action="store_true",
        help="dump the ffmpeg log?"
    )
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
        required=not ignore_requirements,
        nargs="+",
        help="forward source video from which to sample"
    )
    parser.add_argument(
        '-b', "--fpath_in_backward",
        required=not ignore_requirements,
        nargs="+",
        help="backward source video from which to sample"
    )
    parser.add_argument(
        "--frequency",
        default=0.5,
        type=float,
        help="frequency (wrt video length) of sinusoidal timeline"
    )
    parser.add_argument(
        "--markov_p",
        default=0.75,
        type=float,
        help="probability of staying on current video"
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
        default="output.mov",
        help="Output filepath. Should have '.avi' extension if you're still fucking around"
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
    parser.add_argument(
        "--fpath_manifest",
        default=CompressurePersistence.defaults.fpath_manifest,
        help="location of manifest file, which contains all transcode and slice metadata",
    )
    parser.add_argument(
        "--dpath_workdir",
        default=CompressurePersistence.defaults.workdir,
        help="location for intermediate files, such as transcodes and slices"
    )
    parser.add_argument(
        "--n_workers",
        default=0,
        type=int,
        help="number of workers to dispatch for parallelizable operations"
    )
    args = parser.parse_args()
    if not ignore_requirements:
        assert args.scaled or args.rectified
    return args


def main():
    args = parse_args()
    controller = CompressureSystem(
        fpath_manifest=args.fpath_manifest,
        workdir=args.dpath_workdir
    )
    encoder_config = construct_encoder_config(args.encoder, args.encoder_config)
    if args.pre_reverse_loop:
        raise NotImplementedError("reverse-looping needs work. don't use it")
        print("reverse-looping input")
        fpath_in_forward = reverse_loop(args.fpath_in_forward)
        fpath_in_backward = reverse_loop(args.fpath_in_backward)
    else:
        fpath_in_forward = args.fpath_in_forward
        fpath_in_backward = args.fpath_in_backward

    fpaths_encode_forward = [None for _ in fpath_in_forward]
    dpaths_slices_forward = [None for _ in fpath_in_forward]
    fpaths_encode_backward = [None for _ in fpath_in_backward]
    dpaths_slices_backward = [None for _ in fpath_in_backward]

    fpaths_all = [fp for fp in fpath_in_forward]
    fpaths_all.extend(fpath_in_backward)
    # min_fps = get_min_fps(fpaths_all)
    min_pix_fmt = PixelFormatter().get_common_pix_fmt([
        VideoMetadata(fpath).pix_fmt
        for fpath in fpaths_all
    ])

    # For each path provided in forward
    for i, fpath in enumerate(fpath_in_forward):
        # TODO find min fps and min pix_fmt first, convert both in compress step
        fpaths_encode_forward[i] = controller.compress(
            fpath,
            gop_size=args.gop_size,
            encoder=args.encoder,
            encoder_config=encoder_config,
            pix_fmt=min_pix_fmt,
        )
        dpaths_slices_forward[i] = controller.slice(
            fpath_source=fpath,
            fpath_encode=fpaths_encode_forward[i],
            superframe_size=args.superframe_size,
            n_workers=args.n_workers,
        )

    if fpath_in_backward:
        for i, fpath in enumerate(fpath_in_backward):
            fpaths_encode_backward[i] = controller.compress(
                fpath,
                gop_size=args.gop_size,
                encoder=args.encoder,
                encoder_config=encoder_config,
                pix_fmt=min_pix_fmt,
            )
            dpaths_slices_backward[i] = controller.slice(
                fpath_source=fpath,
                fpath_encode=fpaths_encode_backward[i],
                superframe_size=args.superframe_size,
                n_workers=args.n_workers,
            )

    dpaths_slices = zip(dpaths_slices_forward, dpaths_slices_backward)
    buffers = []
    for i, (dpath_slices_forward, dpath_slices_backward) in enumerate(dpaths_slices):

        buffers.append(controller.init_buffer(
            dpath_slices_forward,
            dpath_slices_backward,
            args.superframe_size
        ))

    # TODO pick up here
    initial_state = deepcopy(buffers[0].state)
    timelines = [generate_timeline_function(
        args.superframe_size,
        len(buffer),
        frequency=args.frequency,
        n_superframes=args.n_superframes - 1,
        scaled=args.scaled,
        rectified=args.rectified
    ) for buffer in buffers]

    if timelines[0][0] == initial_state:
        video_list = []
    else:
        video_list = [initial_state]

    # Which buffer is active?
    buffer_index = 0

    step_all = False

    # These should be equal but we take min just in case
    n_locations = min([len(t) for t in timelines])
    for timeline_index in range(n_locations):

        if step_all:
            buffer_states = [
                buffer.step(to=timeline[timeline_index])
                for buffer, timeline in zip(buffers, timelines)
            ]
            video_list.append(buffer_states[buffer_index])
        else:
            video_list.append(buffers[buffer_index].step(to=timelines[buffer_index][timeline_index]))

        if np.random.rand() > args.markov_p:
            buffer_index = (buffer_index + 1) % len(timelines)

    print(f"Concatenating {len(video_list)} videos")
    concat_videos(video_list, fpath_out=args.fpath_out)
    print(args.fpath_out)


def get_min_fps(
    fpaths_in: Sequence[str],
) -> str:
    metadata = [VideoMetadata(str(Path(fpath).expanduser())) for fpath in fpaths_in]
    min_arg = np.argmin([md.framerate for md in metadata])
    return metadata[min_arg].framerate_fractional


if __name__ == "__main__":
    with ipdb.launch_ipdb_on_exception():
        main()
