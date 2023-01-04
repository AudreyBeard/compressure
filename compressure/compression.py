from argparse import ArgumentParser
from pathlib import Path
import logging
from copy import deepcopy
from pprint import pformat

from compressure.dataproc import try_subprocess
from compressure.persistence import VideoCompressionPersistenceDefaults, VideoCompressionPersistence
from compressure.exceptions import EncoderSelectionError

logging.basicConfig(filename='.compression.log', level=logging.DEBUG)


class VideoCompressionDefaults(object):
    workdir = VideoCompressionPersistenceDefaults.workdir
    gop_size = 6000
    encoder = "libx264"
    encoder_config_options = {
        "mpeg4": {},
        "libx264": {
            "preset": "veryfast",
            "qp": -1,
            "bf": 0,
        },
        "libx265": {
            "preset": "veryfast",
            "qp": -1,
            "bf": 0,
        },
        "h264_videotoolbox": {
            "bf": 0,
            "bitrate": "10M",
        },
    }

    @classmethod
    def fallback(cls, encoder, specified_options):
        try:
            full_options = deepcopy(cls.encoder_config_options[encoder])
        except KeyError:
            raise EncoderSelectionError(encoder, cls.encoder_config_options)

        full_options.update(specified_options)
        return full_options


class VideoCompressionSystem(object):
    def __init__(self, fpath_manifest=VideoCompressionPersistenceDefaults.fpath_manifest,
                 workdir=VideoCompressionPersistenceDefaults.workdir,
                 autosave=True,
                 expect_existing_manifest=False):

        self.persistence = VideoCompressionPersistence(
            fpath_manifest=fpath_manifest,
            workdir=workdir,
            autosave=autosave,
            expect_existing_manifest=expect_existing_manifest,
        )

    def compress(self, fpath_in, gop_size, encoder, encoder_config):
        compression = SingleVideoCompression(
            fpath_in=fpath_in,
            workdir=self.persistence.workdir,
            gop_size=gop_size,
            encoder=encoder,
            encoder_config=encoder_config,
        )
        cached = self.persistence.get(compression)

        if cached is None:
            logging.info("No video found in persistent storage - creating now")
            self.persistence.add_compression(compression)
            fpath, _ = compression.transcode_video()
            logging.info(f"Successfully added & transcoded video to {fpath}")
        else:
            logging.info(f"Found {cached['fpath_out']} in persistent storage")
            fpath = cached['fpath_out']

        return fpath

    def save(self):
        self.persistence.save()


class SingleVideoCompression(object):
    def __init__(self, fpath_in, gop_size=None, encoder=None,
                 encoder_config_dict={},
                 workdir=VideoCompressionDefaults.workdir, **kwargs):

        self.workdir = Path(workdir).expanduser()
        self._fpath_in = Path(fpath_in).expanduser()

        self.encoder = VideoCompressionDefaults.encoder if encoder is None else encoder
        self.gop_size = VideoCompressionDefaults.gop_size if gop_size is None else gop_size

        self.encoder_config_dict = VideoCompressionDefaults.fallback(
            self.encoder,
            encoder_config_dict
        )

        self.crop_square = False
        self.fpath_out = self.generate_human_readable_fpath()
        self._transcode_command_list = self.generate_ffmpeg_command()

    @property
    def fpath_in(self):
        return str(self._fpath_in)

    @property
    def human_readable_name(self):
        return self.generate_human_readable_name()

    def generate_human_readable_name(self):
        human_readable_name = self._fpath_in.stem
        human_readable_name += "_transcoded"
        human_readable_name += f"_g={self.gop_size}"
        human_readable_name += f"_{self.encoder}"

        if self.encoder == "libx264":
            human_readable_name += f"_preset={self.encoder_config_dict['preset']}"
            human_readable_name += f"_qp={self.encoder_config_dict['qp']}"
            human_readable_name += f"_bf={self.encoder_config_dict['bf']}"

        elif self.encoder == "h264_videotoolbox":
            human_readable_name += f"_bf={self.encoder_config_dict['bf']}"
            human_readable_name += f"_bitrate={self.encoder_config_dict['bitrate']}"

        if self.crop_square:
            human_readable_name += "_cropped-square"

        human_readable_name += ".avi"

        return human_readable_name

    def generate_human_readable_fpath(self):
        human_readable_name = self.generate_human_readable_name()
        fpath_out = str(Path(self.workdir) / human_readable_name)

        return fpath_out

    def generate_ffmpeg_encoding_params(self, override_dict={}):
        # Ingest specified args, falling back onto defaults if necessary
        configs = VideoCompressionDefaults.fallback(self.encoder, override_dict)

        ffmpeg_args = [self.encoder]

        if self.encoder == "libx264":
            ffmpeg_args.extend([
                "-preset", configs['preset'],
                "-qp", str(configs['qp']),
                "-bf", str(configs['bf']),
            ])
        elif self.encoder == "h264_videotoolbox":
            ffmpeg_args.extend([
                "-bf", str(configs['bf']),
                "-b:v", str(configs['bitrate']),
            ])
        elif self.encoder == "libx265":
            ffmpeg_args.extend([
                # "-tag:v", "hvc1",
            ])
        return ffmpeg_args

    def generate_ffmpeg_command(self):
        # Start construction of FFmpeg command
        command = [
            "ffmpeg", "-y",
            "-v", "error",
            "-i", str(self.fpath_in),
            "-g", str(self.gop_size),
            "-strict", "-2",
            "-c:v",
        ]

        # Generate and populate encoding params
        encoder_params = self.generate_ffmpeg_encoding_params()
        command.extend(encoder_params)

        if self.crop_square:
            command.extend([
                "-filter:v",
                '"crop=ih:ih"'
            ])

        command.append(self.fpath_out)

        return command

    def transcode_video(self):
        logging.info(f"Running command: `{self.transcode_command}`")
        process = try_subprocess(self._transcode_command_list)
        return self.fpath_out, process

    @property
    def transcode_command(self):
        return ' '.join([str(x) for x in self._transcode_command_list])

    def __repr__(self):
        s = self.__class__.__name__
        s += "("
        s += f"fpath_in={self._fpath_in}"
        s += f", gop_size={self.gop_size}"
        s += f", encoder={self.encoder}"
        s += f", encoder_config={pformat(self.encoder_config_dict)}"
        s += f", fpath_out={self.fpath_out}"
        s += ")"
        return s


def parse_args():
    parser = ArgumentParser()
    parser.add_argument(
        "-i", "--fpath_in",
        required=True,
        help="""Input filepath to be compressed using specified encoder options
        and written to .avi output"""
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
        "--encoder-config",
        default="",
        nargs="+",
        help=f"""configuration, in form `key_0 value_0 key_1 value_1...`.
            If left unspecified, default values will be used for the following encoders:
            {pformat(VideoCompressionDefaults.encoder_config_options)}"""
    )
