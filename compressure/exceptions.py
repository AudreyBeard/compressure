from pprint import pformat


class PersistenceOverwriteError(Exception):
    def __init__(self, compressor, *args, **kwargs):
        super().__init__(f"""{compressor} exists in persistence - try using overwrite flag""", *args, **kwargs)


class ExistingSourceError(Exception):
    def __init__(self, manifest_obj, fpath_source):
        super().__init__(f"{fpath_source} already exists in manifest {manifest_obj}")


class InferredAttributeFromFileError(Exception):
    def __init__(self, attribute, fpath, *args, **kwargs):
        super().__init__(f"""{attribute} is inferred from {fpath} and \
            can't be overridden this way""", *args, **kwargs)


class EncoderSelectionError(Exception):
    def __init__(self, encoder, options, *args, **kwargs):
        super().__init__(f"""encoder must be one of {pformat(list(options.keys()))},
            not {encoder}""", *args, **kwargs)


class MalformedConfigurationError(Exception):
    def __init__(self, nargs, *args, **kwargs):
        super().__init__("""--encoder-config must be in form `key_0 value_0 key_1 value_1...`."""
                         f""" You specified {nargs} arguments""",
                         *args, **kwargs)


# TODO make this a warning
class UnrecognizedEncoderConfigError(Exception):
    def __init__(self, encoder, param_name, *args, **kwargs):
        super().__init__(f"Encoder {encoder} doesn't use parameter {param_name}",
                         *args, **kwargs)


class SubprocessError(Exception):
    def __init__(self, process, *args, **kwargs):
        command = " ".join((str(a) for a in process.args))
        super().__init__(f"Subprocess `{command}` failed with the following error: \
            \n{process.stderr}", *args, **kwargs)


class RAMFSDuplicateFileError(Exception):
    def __init__(self, ramfs, fpath, *args, **kwargs):
        super().__init__(f"{ramfs.__class__.__name__} object {ramfs} has already registered file \
            {fpath.name} at {str(fpath)}", *args, **kwargs)
