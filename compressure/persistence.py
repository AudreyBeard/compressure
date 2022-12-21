import os
from pathlib import Path
import json
import logging

from compressure.exceptions import PersistenceOverwriteError

logging.basicConfig(filename='.persistence.log', level=logging.DEBUG)


class VideoPersistenceDefaults(object):
    # Default location is ./.cache
    workdir = Path("~/.cache/compressure/").expanduser()
    fpath_manifest = workdir / "manifest.json"
    version = "0.0"


class VideoCompressionPersistenceDefaults(object):
    # Default location is ./.cache
    workdir = VideoPersistenceDefaults.workdir / "compressions"
    fpath_manifest = workdir / "manifest.json"
    version = "0.1"


class VideoSlicerPersistenceDefaults(object):
    # Default location is ./.cache
    workdir = VideoPersistenceDefaults.workdir / "slices"
    fpath_manifest = workdir / "manifest.json"
    version = "0.0"


class VideoPersistence(object):
    def __init__(self, fpath_manifest=VideoPersistenceDefaults.fpath_manifest,
                 workdir=VideoPersistenceDefaults.workdir,
                 autosave=True, expect_existing_manifest=False, overwrite=False,
                 version=VideoPersistenceDefaults.version):
        self.version = version
        self.fpath_manifest = str(Path(fpath_manifest).expanduser())
        self.workdir = str(Path(workdir).expanduser())
        self.manifest = self._try_read_manifest()
        self.autosave = autosave
        self.overwrite = overwrite
        if self.autosave:
            self.save()

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
                os.makedirs(self.workdir, exist_ok=True)
                os.makedirs(Path(self.fpath_manifest).parent, exist_ok=True)
                manifest = self._init_empty_manifest()

        except json.JSONDecodeError as e:
            logging.error(f"Caught {e} - this usually means the manifest is malformed. Try deleting the offending entry.")
            raise e
        else:
            logging.info(f"Found manifest {self.fpath_manifest} with {len(manifest['encodes'])} entries")
            logging.info(f"""Overriding self.workdir from existing manifest:
                \n{self.workdir} -> {manifest['workdir']}""")
            self.workdir = manifest['workdir']

        return manifest

    def _init_empty_manifest(self):
        """ Initializes empty manifest
        """
        manifest = {
            'workdir': self.workdir,
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

    def __len__(self):
        raise NotImplementedError

    def __getitem__(self, compression):
        raise NotImplementedError

    def get(self, compression):
        raise NotImplementedError

    def __repr__(self):
        s = self.__class__.__name__
        s += f" with {len(self)}"
        s += " entry" if len(self) == 1 else " entries"
        s += f" at {self.fpath_manifest}"
        return s


class VideoCompressionPersistence(VideoPersistence):
    """ Pairs with dataproc.VideoCompression
    """
    def __init__(self, fpath_manifest=VideoCompressionPersistenceDefaults.fpath_manifest,
                 workdir=VideoCompressionPersistenceDefaults.workdir,
                 autosave=True, expect_existing_manifest=False, overwrite=False,
                 version=VideoCompressionPersistenceDefaults.version):

        super().__init__(fpath_manifest=VideoCompressionPersistenceDefaults.fpath_manifest,
                         workdir=VideoCompressionPersistenceDefaults.workdir,
                         autosave=True, expect_existing_manifest=False,
                         overwrite=False,
                         version=VideoCompressionPersistenceDefaults.version)

    def add_compression(self, video_compression):
        """ Add compression to manifest, capturing filepath in (to avoid
            reversing videos redundantly), human-readable name (to avoid
            transcoding videos redundantly)
        """
        human_readable_name = video_compression.human_readable_name
        encodes = self.manifest['encodes'].get(video_compression.fpath_in)

        if encodes is None:
            self.manifest['encodes'][video_compression.fpath_in] = {}

        this_encoding = self.manifest['encodes'][video_compression.fpath_in].get(human_readable_name)
        if this_encoding is None or self.overwrite:
            self.manifest['encodes'][video_compression.fpath_in][human_readable_name] = {
                'fpath_out': video_compression.fpath_out,
                'transcode_command': video_compression.transcode_command,
            }
        else:
            raise PersistenceOverwriteError(video_compression)

        if self.autosave:
            self.save()

    def __len__(self):
        return len(self.manifest['encodes'])

    def _init_empty_manifest(self):
        """ Initializes empty manifest
        """
        manifest = {
            'workdir': self.workdir,
            'encodes': {},
            'version': self.version,
        }
        return manifest

    def __getitem__(self, compression):
        return self.manifest['encodes'][compression.fpath_in][compression.human_readable_name]

    def get(self, compression):
        value = self.manifest['encodes'].get(compression.fpath_in)
        if value is not None:
            value = value.get(compression.human_readable_name)
        return value


class CompressurePersistence(object):
    defaults = VideoPersistenceDefaults

    def __init__(self, fpath_manifest=VideoPersistenceDefaults.fpath_manifest,
                 workdir=VideoPersistenceDefaults.workdir,
                 autosave=True, expect_existing_manifest=False, overwrite=False,
                 version=VideoPersistenceDefaults.version, verbosity=0):
        self.verbosity = verbosity
        self.version = version
        self.fpath_manifest = str(Path(fpath_manifest).expanduser())
        self.workdir = str(Path(workdir).expanduser())
        self.manifest = self._try_read_manifest()
        self.autosave = autosave
        self.overwrite = overwrite
        if self.autosave:
            self.save()

    def _log_print(self, msg, log_op):
        if self.verbosity > 0:
            print(msg)

        log_op(msg)

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
                self._log_print(
                    f"No database found at {self.fpath_manifest}, initializing new manifest",
                    logging.info
                )
                os.makedirs(self.workdir, exist_ok=True)
                os.makedirs(Path(self.fpath_manifest).parent, exist_ok=True)
                manifest = self._init_empty_manifest()

        except json.JSONDecodeError as e:
            logging.error(f"Caught {e} - this usually means the manifest is malformed. Try deleting the offending entry.")
            raise e
        else:
            self._log_print(
                f"Found manifest {self.fpath_manifest} with {len(manifest)} sources",
                logging.info
            )
            self._log_print(
                f"""Overriding self.workdir from existing manifest: \
                    \n{self.workdir} -> {manifest['workdir']}""",
                logging.info
            )
            self.workdir = manifest['workdir']

        return manifest

    def _init_empty_manifest(self):
        """ Initializes empty manifest
        """
        manifest = {
            'workdir': self.workdir,
            'version': self.version,
            'encodes': {},
        }
        return manifest

    def _write_manifest(self, fpath=None):
        if fpath is not None:
            self.fpath_manifest = str(Path(fpath).expanduser())

        with open(self.fpath_manifest, 'w') as fid:
            json.dump(self.manifest, fid)

    def save(self, fpath=None):
        self._write_manifest(fpath)

    def __len__(self):
        return len(self.manifest['encodes'])

    def __getitem__(self, human_readable_name):
        return self.manifest['encodes'][human_readable_name]

    def get(self, human_readable_name):
        return self.manifest['encodes'].get(human_readable_name)

    def __repr__(self):
        s = self.__class__.__name__
        s += f" with {len(self)}"
        s += " entry" if len(self) == 1 else " entries"
        s += f" at {self.fpath_manifest}"
        return s

    def add_compression(self, compression_obj):
        """ Add compression to manifest, capturing filepath in (to avoid
            reversing videos redundantly), human-readable name (to avoid
            transcoding videos redundantly)
        """
        human_readable_name = compression_obj.human_readable_name
        found_data = self.get(human_readable_name)

        if found_data is None or self.overwrite:
            self.manifest['encodes'][human_readable_name] = {
                'fpath_in': compression_obj.fpath_in,
                'fpath_out': compression_obj.fpath_out,
                'transcode_command': compression_obj.transcode_command,
                'slices': dict(),
                'reversed': None,
                'reversed_loop': None,
            }
        else:
            raise PersistenceOverwriteError(compression_obj)

        if self.autosave:
            self.save()

    def get_compression(self, compression_obj):
        human_readable_name = compression_obj.human_readable_name
        found_data = self.get(human_readable_name)
        return found_data

    def add_slices(self, compression_obj, slicer_obj):
        """ Add compression to manifest, capturing filepath in (to avoid
            reversing videos redundantly), human-readable name (to avoid
            transcoding videos redundantly)
        """
        human_readable_name = compression_obj.human_readable_name
        found_data = self.get(human_readable_name)

        if found_data is None:
            self.add_compression(compression_obj)

        slices_dict = self.manifest['encodes'][human_readable_name]['slices']
        slices_dict[slicer_obj.human_readable_string] = {
            'superframe_size': slicer_obj.superframe_size,
            'workdir': slicer_obj.workdir,
        }

        if self.autosave:
            self.save()

    def get_slices(self, compression_obj, slicer_obj):
        cached_compression = self.get_compression(compression_obj)
        if cached_compression is None:
            return None
        else:
            return cached_compression['slices'].get(slicer_obj.human_readable_string)

    def get_reversed(self, compression_obj):
        cached_compression = self.get_compression(compression_obj)
        if cached_compression is None:
            return None

        return cached_compression['reversed']

    def get_reversed_loop(self, compression_obj):
        cached_compression = self.get_compression(compression_obj)
        if cached_compression is None:
            return None

        return cached_compression['reversed_loop']

    def add_reversed(self, compression_obj, fpath_reversed=None, fpath_reversed_loop=None):
        human_readable_name = compression_obj.human_readable_name
        found_data = self.get(human_readable_name)

        if found_data is None:
            self.add_compression(compression_obj)

        self.manifest['encodes'][human_readable_name]['reversed'] = fpath_reversed
        self.manifest['encodes'][human_readable_name]['reversed_loop'] = fpath_reversed_loop

        if self.autosave:
            self.save()
