import logging
import queue
import subprocess
import threading

logger = logging.getLogger(__name__)


def extract_chunk(input_file, start_time, duration):
    """Extract original H.264 frames without re-encoding"""
    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-i', input_file,
        '-c', 'copy',
        '-ss', f"{start_time:.3f}",
        '-t', f"{duration:.3f}",
        '-copyinkf',
        '-bsf:v', 'h264_mp4toannexb',
        '-f', 'h264',
        '-'
    ]
    try:
        result = subprocess.run(ffmpeg_cmd, capture_output=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.info(f"[ffmpeg error] {e.stderr.decode().strip()}")
        return None


class Producer(object):
    def __init__(
        self,
        chunk_q: queue.Queue,
        debug: bool = False,
    ):
        self.chunk_q = chunk_q
        self.debug = debug

    def update(
        self,
        fpath_video: str,
        position: float,
        width: float,
    ):
        chunk = extract_chunk(
            fpath_video,
            position,
            width
        )
        if chunk:
            try:
                self.chunk_q.put(chunk, timeout=1)
                logger.info(f"[p] queued chunk at t={position:.3f}", flush=True)
            except queue.Full:
                logger.info("[p] queue full, skipping", flush=True)
            if self.debug:
                self._log_chunk(chunk)
        else:
            logger.info(f"[p] failed to extract chunk at t={position:.2f}", flush=True)

    def _log_chunk(
        self,
        chunk,
        logfile: str = "logs/stream.producer.log"
    ):
        with open(logfile, 'ab') as fid:
            fid.write(chunk)


class Consumer(object):
    def __init__(
        self,
        fpath_video_init: str,
        chunk_q: queue.Queue,
        width_init: float = 0.5,
        debug: bool = False
    ):
        self.set_initial_chunk(fpath_video_init, width_init)
        self.chunk_q = chunk_q
        self.debug = debug

    def start(
        self,
    ):
        """Streams chunks to ffplay for playback"""
        ffplay_proc = subprocess.Popen(
            ['ffplay', '-loglevel', 'quiet', '-fflags', 'nobuffer', '-f', 'h264', '-'],
            stdin=subprocess.PIPE
        )

        ffplay_proc.stdin.write(self.init_chunk)
        ffplay_proc.stdin.flush()
        logger.info("[c] wrote initial chunk to ffplay")
        if self.debug:
            self._log_chunk(self.init_chunk)
        try:
            while True:
                chunk = self.chunk_q.get()
                ffplay_proc.stdin.write(chunk)
                ffplay_proc.stdin.flush()
                logger.info(f"[c] played chunk ({len(chunk)} bytes)", flush=True)
                if self.debug:
                    self._log_chunk(chunk)

        except BrokenPipeError:
            logger.info("[c] ffplay exited.")
        finally:
            ffplay_proc.terminate()

    def set_initial_chunk(
        self,
        fpath_video: str,
        width: float
    ):
        self.init_chunk = extract_chunk(fpath_video, 0, width)

    def _log_chunk(
        self,
        chunk,
        logfile: str = "logs/stream.consumer.log"
    ):
        with open(logfile, 'ab') as fid:
            fid.write(chunk)


if __name__ == "__main__":
    """ Simple demo, assumes input.mp4 exists and is well-formatted for ingestion
    """

    VIDEO_FILE = "input.mp4"
    CHUNK_DURATION = 0.5
    CHUNK_STEP = CHUNK_DURATION / 2

    chunk_queue = queue.Queue(maxsize=10)
    producer = Producer(chunk_queue)
    consumer = Consumer(VIDEO_FILE, chunk_queue)

    # Start producer thread
    threading.Thread(target=consumer.start, daemon=True).start()

    # Run consumer in main thread
    t = 0.0
    while True:
        producer.update(
            VIDEO_FILE,
            t,
            CHUNK_DURATION
        )
        t += CHUNK_STEP
