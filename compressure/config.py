from pathlib import Path
import logging


APP_NAME = "Compressure"

LOG_FPATH = str(Path(f".{APP_NAME.lower()}.log").expanduser())
LOG_LEVEL = logging.DEBUG
