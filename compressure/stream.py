import os
import subprocess
import socket

from compressure.persistence import VideoPersistenceDefaults


class StreamingDefaults(object):
    input_path = VideoPersistenceDefaults.workdir / "input.avi"
    output_path = VideoPersistenceDefaults.workdir / "output.avi"
    fpath_playlist = VideoPersistenceDefaults.workdir / "ffmpeg_concat_playlist.txt"
    socket_fpath = "unix:/tmp/ffmpeg.sock"


class InfinitePlaylist(object):
    def __init__(self, fpath_default="", n_videos=2, force=False):
        self.fpath = StreamingDefaults.fpath_playlist
        self.n_videos = n_videos
        self.state = 0
        self.fpath_default = fpath_default

        try:
            self._init_files()
        except FileExistsError as e:
            if force:
                self.cleanup()
                self._init_files()
            else:
                raise e

    def _init_files(self):
        with open(self.fpath, 'w') as fid:
            fid.write("ffconcat version 1.0")
            for i in range(self.n_videos):
                fid.write(f"file {self._tempfile_path(i)}")
        for i in range(self.n_videos):
            self.next_video(self.fpath_default)

    def next_video(self, fpath):
        self.state = (self.state + 1) % self.n_videos
        symlink = self._tempfile_path(self.state)
        if os.path.islink(symlink):
            os.remove(symlink)
        os.symlink(fpath, symlink)

    def _tempfile_path(self, index):
        return f"tempfile_{index}.avi"

    def cleanup(self):
        try:
            os.remove(self.fpath)
        except FileNotFoundError:
            pass

        for i in range(self.n_videos):
            try:
                os.remove(self._tempfile_path(i))
            except FileNotFoundError:
                pass

    def __del__(self):
        self.cleanup()

    def __delete__(self):
        self.cleanup()


def ffplay(fpath):
    subprocess.run(f"ffplay {fpath}".split(), check=True)


def concat_stream(fpath, address):
    command = [
        "ffmpeg", "-re",
        "-stream_loop", "-1",
        "-i", fpath,
        "-flush_packets", "0",
        "-f", "mpegts",
        "-listen", "1",
        address
    ]

    subprocess.run(command, check=True, shell=True)


def server():
    fpath_socket = "/tmp/ffmpeg.sock"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    if os.path.exists(fpath_socket):
        os.remove(fpath_socket)
    s.bind(fpath_socket)

    print("S: waiting for connection")
    s.listen()

    while True:
        connection, address = s.accept()
        print(f"connected at {address}")
        connection.send("server saying hi".encode())
        connection.close()


def client():
    fpath_socket = "/tmp/ffmpeg.sock"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    s.bind(fpath_socket)

    print("C: waiting for connection")
    s.listen(5)

    while True:
        connection, address = s.accept()
        print(f"got connection from {address}")
        connection.send("client's saying hi".encode())
        connection.close()


def both():
    parent, child = socket.socketpair()

    pid = os.fork()

    if pid:
        try:
            os.remove("input-pipe.avi")
        except FileNotFoundError:
            pass
        os.mkfifo("input-pipe.avi")
        print('in parent, sending message')
        child.close()
        command = "ffmpeg -i /Users/audrey/data/video/output/output.avi -c:v copy -f image2pipe -"
        proc = subprocess.run(command.split(), capture_output=True)
        parent.sendall(proc.stdout)
        # response = parent.recv(1024)
        print('S: Done sending')
        parent.close()

    else:
        os.remove("pipe.avi")
        os.mkfifo("pipe.avi")
        print('in child, waiting for message')
        parent.close()
        print(dir(child))
        print(child.getsockname())
        message = child.recv(4096)
        print("C: read something")
        with open("pipe.avi", 'wb') as fid:
            fid.write(message)
        print("C: Wrote")
        subprocess.run(["ffplay", "pipe.avi"])
        print("C: ffplayed")
        while message:
            message = child.recv(4096)
            with open("pipe.avi", 'wb') as fid:
                fid.write(message)
        # print('message from parent:', str(message))
        # child.sendall(b'pong')
        child.close()


def play():
    command = "ffmpeg -i /Users/audrey/data/video/output/output.avi -t 2 -c:v copy -f image2pipe -"
    sender = subprocess.run(command.split(), capture_output=True)
    # sender = subprocess.run(command.split(), capture_output=True)
    player = subprocess.Popen(["ffplay", "-"], stdin=subprocess.PIPE)
    player.communicate(input=sender.stdout)
    sender_b = subprocess.run(
        "ffmpeg -i /Users/audrey/data/video/output/output.avi -ss 3 -t 4 -c:v copy -f image2pipe -".split(),
        capture_output=True
    )

    player.communicate(input=sender_b.stdout)
