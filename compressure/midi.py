from collections import deque

from mido.backends._parser_queue import ParserQueue
import mido

#print(dir(mido.backends.backend.Backend))

def test_nanokontrol():
    with mido.open_input('nanoKONTROL2 SLIDER/KNOB') as inport:
        while True:
            msg = inport.poll()
            if msg:
                print(msg)


class ParserDeque(ParserQueue):
    """ Designed to be a drop-in replacement for
        mido.backends.rtmidi.Input._queue, which only returns the most recent
        message
    """
    def __init__(self):
        super().__init__()
        self._queue = deque()

    def put(self, msg):
        self._queue.append(msg)

    def get(self):
        return self._queue.pop()

    def poll(self):
        try:
            return self._queue.pop()
        except IndexError:
            return None
