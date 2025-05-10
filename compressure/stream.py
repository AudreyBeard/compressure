import logging
import queue
import subprocess
import threading


logger = logging.getLogger(__name__)


def extract_chunk(input_file, start_time, duration):
    """ Extract original H.264 frames without re-encoding
        In my tests on an Apple M1 Pro, it seems like this decode consistently takes:
        - at least 0.22 seconds
        - less than 0.72 seconds
        - on average, 0.24 seconds
        This means it's unsuitable for immediate seeking & serving of chunks less than ~0.25s
        Moving forward, we could:
        - serve a lot of chunks into the queue until we're confident it's enough (~0.5s worth is probably mostly fine)
        - buffer a larger window into memory and serve chunks from there
        - rely on faster decoding processes
    """
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
        raise ValueError(e.stderr.decode().strip())


class Producer(object):
    def __init__(
        self,
        chunk_q: queue.Queue,
        repeat_chunks: bool = False,
        repeat_chunks_for_sec: float = 0.5,
        debug: bool = False,
    ):
        self.chunk_q = chunk_q
        self.debug = debug
        self.repeat_chunks = repeat_chunks
        self.repeat_chunks_for_sec = repeat_chunks_for_sec

    def update(
        self,
        fpath_video: str,
        position: float,
        width: float,
    ):
        logger.info(f"[p] extracting chunk at t={position:.3f}")
        chunk = extract_chunk(
            fpath_video,
            position,
            width
        )
        if chunk:
            n_copies = int(int(self.repeat_chunks) * (self.repeat_chunks_for_sec / width**2))
            try:
                self.chunk_q.put(chunk, timeout=1)
                logger.info(f"[p] queued chunk at t={position:.3f}")
                # I'm not totally sure if this or the Consumer's replication is doing the most work here
                for i in range(n_copies):
                    self.chunk_q.put(chunk, timeout=1)
                    # logger.info(f"[p] queued another chunk at t={position:.3f}")

            except queue.Full:
                logger.info("[p] queue full, skipping")
                #raise queue.Full
            if self.debug:
                self._log_chunk(chunk)
        else:
            logger.info(f"[p] failed to extract chunk at t={position:.2f}")

    def _log_chunk(
        self,
        chunk,
        logfile: str = "stream.producer.log"
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
        threading.Thread(target=self._start, daemon=True).start()

    def _start(
        self,
    ):
        """Streams chunks to ffplay for playback"""
        logger.info("[c] starting ffplay")
        ffplay_proc = subprocess.Popen(
            ['ffplay', '-loglevel', 'quiet', '-fflags', 'nobuffer', '-f', 'h264', '-'],
            stdin=subprocess.PIPE
        )

        logger.info("[c] playing initial chunk")
        ffplay_proc.stdin.write(self.init_chunk)
        ffplay_proc.stdin.flush()
        logger.info("[c] played initial chunk")

        if self.debug:
            logger.debug("[c] writing initial chunk to debug file")
            self._log_chunk(self.init_chunk)
        try:
            while True:
                logger.info("[c] getting chunk from queue")
                chunk = self.chunk_q.get()
                logger.info(f"[c] playing chunk ({len(chunk)} bytes)")
                ffplay_proc.stdin.write(chunk)
                ffplay_proc.stdin.flush()

                # If the queue is empty, just stall
                # I'm not totally sure if this or the Producer's replication is doing the most work here
                while self.chunk_q.empty():
                    #raise queue.Empty
                    #logger.info(f"[c] queue empty; playing chunk ({len(chunk)} bytes)")
                    ffplay_proc.stdin.write(chunk)
                    ffplay_proc.stdin.flush()

                logger.info(f"[c] played chunk ({len(chunk)} bytes)")
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
        logfile: str = "stream.consumer.log"
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
    threading.Thread(target=consumer._start, daemon=True).start()

    # Run consumer in main thread
    t = 0.0
    while True:
        producer.update(
            VIDEO_FILE,
            t,
            CHUNK_DURATION
        )
        t += CHUNK_STEP
