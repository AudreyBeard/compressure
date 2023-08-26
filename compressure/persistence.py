import os
from pathlib import Path
import json
import logging
from typing import Optional, Union

from compressure.exceptions import PersistenceOverwriteError, ExistingSourceError

logging.basicConfig(filename='.persistence.log', level=logging.DEBUG)


class VideoPersistenceDefaults(object):
    # Default location is ./.cache
    workdir = Path("~/.cache/compressure/").expanduser()
    fpath_manifest = workdir / "manifest.json"
    version = "1.0"


class VideoCompressionPersistenceDefaults(object):
    # Default location is ./.cache
    workdir = VideoPersistenceDefaults.workdir / "encodes"
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
    version = VideoPersistenceDefaults.version

    def __init__(self, fpath_manifest=VideoPersistenceDefaults.fpath_manifest,
                 workdir=VideoPersistenceDefaults.workdir,
                 autosave=True, expect_existing_manifest=False, overwrite=False,
                 verbosity=0):
        self.verbosity = verbosity
        self.manifest = CompressureManifest(
            fpath=fpath_manifest,
            autosave=autosave,
            verbosity=verbosity
        )

        # This is where we'll dump encodes
        self.workdir = str(Path(workdir).expanduser())
        os.makedirs(self.workdir, exist_ok=True)

        self.autosave = autosave
        self.overwrite = overwrite
        if self.autosave:
            self.save()

    def _log_print(self, msg, log_op):
        if self.verbosity > 0:
            print(msg)

        log_op(msg)

    def save(self):
        self.manifest.save()

    def __len__(self):
        return len(self.manifest)

    def __getitem__(self, fpath_source):
        return self.manifest[fpath_source]

    def __repr__(self):
        s = self.__class__.__name__
        s += f" with {len(self)}"
        s += " entry" if len(self) == 1 else " entries"
        s += f" at {self.manifest.fpath}"
        return s

    def get_encode(self, fpath_source: str, fpath_encode: str) -> dict:
        return self.manifest.get_encode(fpath_source, fpath_encode)

    def remove_encode(self, fpath_source: str, fpath_encode: str) -> None:
        os.remove(fpath_encode)
        self.manifest.remove_encode(fpath_source, fpath_encode)

    def init_slices_dir(self, fpath_encode: str, superframe_size: int) -> str:
        slices_dir = self.manifest.get_slices_dir(fpath_encode, superframe_size)
        os.makedirs(slices_dir, exist_ok=True)
        return slices_dir

    def add_slices(self, fpath_source: str, fpath_encode: str, superframe_size: int):
        """ Add slices to manifest, capturing filepath in (to avoid
            reversing videos redundantly), human-readable name (to avoid
            transcoding videos redundantly)
        """
        try:
            slices = self.manifest.get_slices(fpath_source, fpath_encode, superframe_size)
        except KeyError:
            slices = self.manifest.add_slices(fpath_source, fpath_encode, superframe_size)

        if self.autosave:
            self.save()

        return slices

    def get_slices(self, fpath_source: str, fpath_encode: str, superframe_size: int) -> dict:
        return self.manifest.get_slices(fpath_source, fpath_encode, superframe_size)

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

    def __getattr__(self, attr):
        try:
            rc = self.__getattribute__(attr)
        except AttributeError:
            rc = self.manifest.__getattribute__(attr)
        return rc


class CompressureManifest(object):
    defaults = VideoPersistenceDefaults
    version = "1.0"

    def __init__(self, fpath: Optional[str] = None,
                 autosave: bool = True, verbosity: int = 1):
        fpath = fpath if fpath is not None else self.defaults.fpath_manifest

        self.fpath = Path(fpath).expanduser()
        self.autosave = autosave
        self.verbosity = verbosity

        self._sources, self._encodes, self._slices = None, None, None

        self._try_read()

    def _log_print(self, msg, log_op):
        """ Logs message according to log_op, which is a function, e.g.:
            - logging.info
            - logging.debug
            - logging.error
            Also prints if this object is verbose
        """
        if self.verbosity > 0:
            print(msg)

        log_op(msg)

    def _try_read(self):
        """ Tries to read the manifest, and instantiates a new one if it can't find it
        """
        try:
            with open(str(self.fpath), 'r') as fid:
                payload = json.load(fid)
        except FileNotFoundError:
            self._log_print(
                f"No manifest file found at {self.fpath}, initializing new manifest",
                logging.info
            )
            payload = self._empty_payload

        except json.JSONDecodeError as e:
            self._log_print(
                f"Caught {e} - this usually means the manifest is malformed. Try deleting the offending entry.",
                logging.error
            )
            raise e
        except KeyError as e:
            self._log_print(
                f"Caught {e} - this usually means the manifest at {self.fpath} is an older version than this one {self.version}. Consider renaming the old one.",
                logging.error
            )
            raise e
        else:
            msg = f"Found manifest at {self.fpath} with {len(payload['sources'])} source"
            msg += "s" if len(payload['sources']) > 1 else ""
            self._log_print(
                msg,
                logging.info
            )

        self.data = payload

    @property
    def _empty_payload(self):
        """ Initializes an empty payload, usually when someone first uses compressure
        """
        payload = {
            'version': self.version,
            'sources': {},
        }
        return payload

    def save(self):
        """ Saves the manifest as a JSON file
        """
        with open(str(self.fpath), 'w') as fid:
            json.dump(self.data, fid)

    def get_source(self, fpath: str) -> dict:
        """ Gets the source entry for specified filepath, the root of all other
            derivative files
        """
        source_name = Path(fpath).name
        try:
            source = self.data['sources'][source_name]
        except KeyError:
            source_name = Path(fpath).name
            msg = f"Didn't find source {source_name} in manifest"
            raise KeyError(msg)
        return source

    def get_encode(self, fpath_source: str, fpath_encode: str) -> dict:
        """ Gets the encode entry for specified source and encode filepaths,
            encodes are the first opportunity for users to manipulate the video
        """
        source = self.get_source(fpath_source)
        encode_name = Path(fpath_encode).name
        try:
            encode = source['encodes'][encode_name]
        except KeyError:
            source_name = Path(fpath_source).name
            msg = f"Didn't find encode {encode_name} for source {source_name} in manifest"
            raise KeyError(msg)

        return encode

    def get_slices(self, fpath_source: str, fpath_encode: str, superframe_size: int) -> dict:
        """ Gets slices entry for source and encode filepaths and superframe
            size. This is the second opportunity for users to manipulate the
            video
        """
        encode = self.get_encode(fpath_source, fpath_encode)

        # Need two try-except clauses because JSON decoding doesn't do ints well
        try:
            slices = encode['slices']['superframe_size'][superframe_size]
        except KeyError:
            try:
                slices = encode['slices']['superframe_size'][str(superframe_size)]
            except KeyError:
                encode_name = Path(fpath_encode).name
                msg = f"Didn't find slices with superframe-size {superframe_size} for encode {encode_name} in manifest"  # noqa
                raise KeyError(msg)

        return slices

    def get_slices_dir(self, fpath_encode: str, superframe_size: int) -> str:
        """ Gets the directory for a specific slice scheme on an encode
            NOTE this may be a good candidate for a mounted RAMFS for a cache
        """
        dpath_slices = Path(fpath_encode).parent.parent / 'slices'
        dpath_parent = dpath_slices / Path(fpath_encode).stem / f'superframe-size={superframe_size}'
        return dpath_parent

    def add_source(self, fpath: str) -> dict:
        """ Adds a source file to the manifest with empty fields
        """
        fname = Path(fpath).name
        if self.data['sources'].get(fname) is not None:
            raise ExistingSourceError(self, fpath)

        self.data['sources'][fname] = {
            'fpath': fpath,
            'encodes': {},
            'reversals': {},
            'reverse_loops': {},
        }

        if self.autosave:
            self.save()

        # Reset lazy evaluation
        self._sources = None

        return self.get_source(fpath)

    def add_encode(self, fpath_source: str, fpath_encode: str, parameters: dict,
                   command: Optional[str] = None) -> dict:
        """ Adds a specific encode to a source entry, with empty slices field
        """
        try:
            source = self.get_source(fpath_source)
        except KeyError:
            source = self.add_source(fpath_source)

        encode_name = Path(fpath_encode).name
        source['encodes'][encode_name] = {
            'fpath': fpath_encode,
            'parameters': parameters,
            'command': command,
            'slices': {'superframe_size': {}},
        }
        if self.autosave:
            self.save()

        # Reset lazy evaluation
        self._encodes = None

        return self.get_encode(fpath_source, fpath_encode)

    def add_slices(self, fpath_source: str, fpath_encode: str, superframe_size: int) -> dict:
        """ Adds a slice scheme to an encode entry
        """
        try:
            encode = self.get_encode(fpath_source, fpath_encode)
        except KeyError:
            source_name = Path(fpath_source).name
            encode_name = Path(fpath_encode).name
            msg = f"Didn't find encode {encode_name} for source {source_name} in manifest"
            raise KeyError(msg)

        encode = self.get_encode(fpath_source, fpath_encode)
        if len(encode['slices'].get('superframe_size', {})) > 0:
            encode['slices']['superframe_size'].update({
                superframe_size: str(self.get_slices_dir(fpath_encode, superframe_size))
            })
        else:
            encode['slices']['superframe_size'] = {
                superframe_size: str(self.get_slices_dir(fpath_encode, superframe_size))
            }

        # Reset lazy evaluation
        self._slices = None

        return self.get_slices(fpath_source, fpath_encode, superframe_size)

    def __len__(self) -> int:
        return len(self.data['sources'])

    def __getitem__(self, source: str) -> dict:
        return self.get_source(source)

    def __repr__(self) -> str:
        return str(self.data)

    @property
    def sources(self) -> list:
        """ Simplified representation of source files in manifest, lazily evaluated
        """
        if self._sources is None:
            self._sources = list(self.data['sources'].keys())
        return self._sources

    @property
    def encodes(self) -> dict:
        """ Simplified representation of encodes in manifest, lazily evaluated
        """
        if self._encodes is None:
            self._encodes = {
                source: list(self.data['sources'][source]['encodes'].keys())
                for source in self.sources
            }
        return self._encodes

    @property
    def slices(self) -> dict:
        """ Simplified representation of encode slices in manifest, lazily evaluated
        """
        if self._slices is None:
            self._slices = {
                source_name: {
                    encode_name: {
                        superframe_size: self._index_into_data(
                            source_name=source_name,
                            encode_name=encode_name,
                            superframe_size=superframe_size
                        )
                        for superframe_size in self._index_into_data(
                            source_name=source_name,
                            encode_name=encode_name
                        )['slices']['superframe_size'].keys()
                    }
                    for encode_name in self.encodes[source_name]
                }
                for source_name in self.sources
            }
        return self._slices

    def remove_source(self, fpath_source: str) -> dict:
        source_name = Path(fpath_source).name
        del self.data['sources'][source_name]
        if self.autosave:
            self.save()

        self._sources = None
        _ = self.sources

        return self.data['sources']

    def remove_encode(self, fpath_source: str, fpath_encode: str) -> dict:
        source_name = Path(fpath_source).name
        encode_name = Path(fpath_encode).name
        del self.data['sources'][source_name]['encodes'][encode_name]
        if self.autosave:
            self.save()

        self._encodes = None
        _ = self.encodes

        return self.data['sources'][source_name]

    def _index_into_data(self, source_name: str,
                         encode_name: Optional[str] = None,
                         superframe_size: Optional[int] = None
                         ) -> Union[dict, str]:
        """ Indexes into underlying data structure according to what parameters are passed in
        """
        # Assume we're done at each index until proven otherwise
        source = self.data['sources'][source_name]
        retval = source

        if encode_name:
            encode = source['encodes'][encode_name]
            retval = encode

        if superframe_size:
            assert encode_name
            slices = encode['slices']['superframe_size'][superframe_size]
            retval = slices

        return retval
