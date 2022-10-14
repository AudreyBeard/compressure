import os
from pathlib import Path
import json
import logging

from compressure.exceptions import CompressorFoundInPersistenceError

logging.basicConfig(filename='.persistence.log', level=logging.DEBUG)


class VideoCompressorPersistenceDefaults(object):
    # Default location is ./.cache
    dpath_data = Path("~/.cache/compressure/video-compressor").expanduser()
    fpath_manifest = dpath_data / "manifest.json"
    version = "0.1"


class VideoCompressorPersistence(object):
    """ Pairs with dataproc.VideoCompressor
    """
    def __init__(self, fpath_manifest=VideoCompressorPersistenceDefaults.fpath_manifest,
                 dpath_data=VideoCompressorPersistenceDefaults.dpath_data,
                 autosave=True, expect_existing_manifest=False, overwrite=False,
                 version=VideoCompressorPersistenceDefaults.version):
        self.version = version
        self.fpath_manifest = str(Path(fpath_manifest).expanduser())
        self.dpath_data = str(Path(dpath_data).expanduser())
        self.manifest = self._try_read_manifest()
        self.autosave = autosave
        self.overwrite = overwrite
        if self.autosave:
            self.save()

    def add_compressor(self, video_compressor):
        """ Add compressor to manifest, capturing filepath in (to avoid
            reversing videos redundantly), human-readable name (to avoid
            transcoding videos redundantly)
        """
        human_readable_name = video_compressor.human_readable_name
        encodes = self.manifest['encodes'].get(video_compressor.fpath_in)

        if encodes is None:
            self.manifest['encodes'][video_compressor.fpath_in] = {}

        this_encoding = self.manifest['encodes'][video_compressor.fpath_in].get(human_readable_name)
        if this_encoding is None or self.overwrite:
            self.manifest['encodes'][video_compressor.fpath_in][human_readable_name] = {
                'fpath_out': video_compressor.fpath_out,
                'transcode_command': video_compressor.transcode_command,
            }
        else:
            raise CompressorFoundInPersistenceError(video_compressor)

        if self.autosave:
            self.save()

    def __len__(self):
        return len(self.manifest['encodes'])

    def _try_read_manifest(self, fpath=None, expect_existing_manifest=False):
        """ Tries to read manifest at specified location (defaults to self.fpath_manifest).
            Initializes empty manifest if no manifest found
        """
        if fpath is not None:
            self.fpath_manifest = str(Path(fpath).expanduser())

        try:
            with open(self.fpath_manifest, 'r') as fid:
                manifest = json.load(fid)
        except FileNotFoundError as e:
            if expect_existing_manifest:
                raise e
            else:
                logging.info(f"No database found at {self.fpath_manifest}, initializing new manifest")
                os.makedirs(self.dpath_data, exist_ok=True)
                os.makedirs(Path(self.fpath_manifest).parent, exist_ok=True)
                manifest = self._init_empty_manifest()

        except json.JSONDecodeError as e:
            logging.error(f"Caught {e} - this usually means the manifest is malformed. Try deleting the offending entry.")
            raise e
        else:
            logging.info(f"Found manifest {self.fpath_manifest} with {len(manifest)} entries")
            logging.info(f"""Overriding self.dpath_data from existing manifest: \
                {self.dpath_data} -> {manifest['dpath_data']}""")
            self.dpath_data = manifest['dpath_data']

        return manifest

    def _init_empty_manifest(self):
        """ Initializes empty manifest
        """
        manifest = {
            'dpath_data': self.dpath_data,
            'encodes': {},
            'version': self.version,
        }
        return manifest

    def _write_manifest(self, fpath=None):
        if fpath is not None:
            self.fpath_manifest = str(Path(fpath).expanduser())

        with open(self.fpath_manifest, 'w') as fid:
            json.dump(self.manifest, fid)

    def save(self, fpath=None):
        self._write_manifest(fpath)

    def __getitem__(self, compressor):
        return self.manifest['encodes'][compressor.human_readable_name]

    def get(self, compressor):
        return self.manifest['encodes'].get(compressor.human_readable_name)

    def __repr__(self):
        s = self.__class__.__name__
        s += f" with {len(self)}"
        s += " entry" if len(self) == 1 else " entries"
        s += f" at {self.fpath_manifest}"
        return s
