# Overview
Compressure is a tool for video creation that hacks the time-dependence
properties of video compression codecs (H.264, MPEG-4, etc.) by manipulating
the frame timeline to break motion-estimation for new forms of movement.

## The simplest way of explaining what's happening  
Video compression codecs take advantage of both spatial and temporal
redundancies, to encode images and motion by referencing other parts of the
image or timeline. Let's start with images, then move to the video domain:

Images are composed of high-frequency components (quickly changing colors or
light intensity in space) and low-frequency components (solid blocks of color
or light). A fine checkerboard, detailed hair or fur, and the texture of leaves
on a tree from afar, are all  examples of high-frequency spatial data. A clear
sky or a single-color shirt are examples of low-frequency spatial data.
Low-frequency spatial data can be encoded much more efficiently than
high-frequency data, because it's less costly to say "take this color and apply
it to this whole area" than to encode individual pixels (or represent an
arbitrarily complex function). The specifics of this are somewhat more complex,
but this simplification will do just fine for now.

Videos are obviously composed of images, so image compression ideas come into
play here as well. However, since videos have a temporal component to them, we
can exploit redundancies there too. A fast-paced image sequence, where subjects 
appear and disappear quickly, requires encoding whole sections of images from
scratch. But if motion is small, or gradual, or non-existent, then we may
encode a frame as "the same as the last frame, with these pixels moving in this
direction," which is much more efficient. The simplest (though impractical for
several reasons) implementation involves encoding only the first image in a
sequence, then encoding the rest as a modification on the first. This creates a
cascading chain of dependencies, where each frame is derivative of previous
frames. We'll discuss the impracticalities of this particular implementation
later, but its close enough to continue the conversation now.

With each of these models of compression, we encode a few components:
- Approximation of spatial or temporal function
  - e.g. 2D function over image patch, or back-references to previous frames
- Error or residual term, applied to the approximation to correct it for this
  particular data

The question that Compressure answers is "what happens if you interrupt this
chain of temporal dependencies?" If we skip frames, or duplicate frames,
without adjusting the motion or residual estimation, we introduce artifacts
that cascade through the image sequence, producing unexpected and unique
videos. Compressure does this by encoding a source video according to
user-defined parameters, slicing the compressed video it into "superframes," or
short collections of consecutive frames (1-10 frames, for instance), then
moving through the timeline of superframes in a way that repeats or skips
superframes, introducing artifacts and slowing or speeding-up movement.

# Quickstart
The following assumes the reader is using MacOS or a Debian derivative and is relatively familiar with managing their machine. We don't currently support Windows, and if you use something like CentOS, BSD, or Arch, you can likely figure out how to translate these commands.

## Installation
First of all, make sure you have `ffmpeg` installed - on MacOS, you can use
`brew install ffmpeg`, and on Debian derivatives you can use `apt-get install
ffmpeg`. You don't need anything special here, so the builds distributed in
these main channels will suffice.

We strongly recommend using virtual environments. You can use any virtual
environment system you like, but we build and test with `python -m venv
VIRTUAL_ENVIRONMENT_PATH`. Make sure you're using Python 3.7+.

To install, simply activate your venv and run:
```bash
pip install -r requirements.txt
pip install .
```

## Running
The easiest entrypoint is `main.py`. You can run this in an interactive Python session (we prefer IPython), or straight from the command line.

Note that you'll need some source videos to run any of these. That's kinda what this whole project is about. We suggest starting with short videos (10-30 seconds).

### Note about Default Values
Compressure defaults to filesystem locations, encoding schemes, and hyperparameters that are supposed to be understandable, interesting, and fast. In general, we try to keep default parameters in a simple class within the module in which they're relevant, with class names like `VideoPersistenceDefaults` and `VideoCompressionDefaults`. This may change at some point. Below are some examples:
- cached files (including the manifest file, a JSON file that keeps track of cached files) go to `~/.cache/compressure` unless specified otherwise
- encoded videos are dropped into the `$CACHE/encodes` by default, where `$CACHE` is the location specified above.
- videos are encoded with `libx264` unless specified otherwise
- encoding parameters (listed below as ffmpeg commands:
    - `-c:v libx264 -preset veryfast -qp -1 -bf 0`:
        - `libx264` is the default codec for [H.264 in FFmpeg](https://trac.ffmpeg.org/wiki/Encode/H.264).
        - `-preset` is a [coarse setting that loosely governs the trade-off between encode speed and compression efficiency](https://trac.ffmpeg.org/wiki/Encode/H.264#Preset)
        - `-qp` is the [quantization parameter](https://slhck.info/video/2017/03/01/rate-control.html), which governs how fine the details are. Changing this has a large impact on the end results
        - `-bf` is the max number of [bidirectional interframes (or B-frames)](https://en.wikipedia.org/wiki/Inter_frame#B-frame). We usually set this to 0 to avoid stuttering.
    - `-c:v mpeg4`
    - `-c:v h264_videotoolbox -bf 0 -b:v 10M`:
        - `h264_videotoolbox` is the [MacOS hardware-accelerated codec for H.264](https://developer.apple.com/documentation/videotoolbox). In our experiments with it in this context, it's not particularly impactful
        - `-b:v` is the target bitrate, which we specify as `bitrate` in Python for readability
    - GoP size is the "group of pictures" size, specifying the maximum number of frames to place between intra-frames. Lower numbers will "reset" the video to a normal-looking state more frequently, higher numbers will propagate artifacts for longer (more abstract). This corresponds to the ffmpeg option `-g`


### Note about persistent caching
The compressure system makes extensive use of persistent caching to avoid
redunant encoding and slicing operations. By default, these are kept in
`~/.cache/compressure` and tracked in `~/.cache/compressure/manifest.json`.

The `compressure.persistence.CompressurePersistence` class is the object we use
for tracking all these versions. Unfortunately, the manifest doesn't
automatically scan the persistence directory at startup, so any versions
deleted outside the Compressure app won't be reflected in the manifest. The
best way to add or remove entries to the persistent cache is to use the
persistence object referenced at the top of this paragraph.

You can manually set the persistence directory by specifying `fpath_manifest`
and `workdir` when instantiating the `compressure.main.CompressureSystem`
object. There is currently no command-line support for this operation.


### Interactive Python Session
This is the "manual" mode that gives you the most control and responsibility. It is the preferred mode of development. The specifics will be different based on your system, but it likely will look something like this:

#### Using Default values
```python
from compressure.main import CompressureSystem
controller = CompressureSystem()

# Forward and backward videos - could be different sources entirely!
fpath_source_fwd = "~/data/video/input/blooming-4.mov"
fpath_source_back = "~/data/video/input/blooming-4_reverse.mov"

# Encode both - may replace all references to "compression" with "encoding"
fpath_encode_fwd = controller.compress(fpath_source_fwd)
fpath_encode_back = controller.compress(fpath_source_back)

dpath_slices_fwd = controller.slice(
    fpath_source=fpath_source_fwd,
    fpath_encode=fpath_encode_fwd,
    superframe_size=6,
)
dpath_slices_back = controller.slice(
    fpath_source=fpath_source_back,
    fpath_encode=fpath_encode_back,
    superframe_size=6,
)

# Create "buffer" of all superframes, for scrubbing through the timeline by superframes
buffer = controller.init_buffer(dpath_slices_fwd, dpath_slices_back, superframe_size=6)

# Generate a timeline function, establishing how we're moving through the timeline.
# TODO we want this to be controlled live, rather than a predefined function like so
timeline = generate_timeline_function(6, len(buffer), frequency=0.5, n_superframes=100)

# Now use the timeline to step/traverse through the video buffer
video_list = [deepcopy(buffer.state)]
for loc in timeline:
    video_list.append(buffer.step(to=loc))

# Finally, concatenate the videos!
concat_videos(video_list, fpath_out="~/data/video/output/output.mov")
```

We don't currently have a more tightly-integrated traversal tool, because we're
hoping to replace it with something more playable. Unfortunately, this means
we're not putting much energy into tightening-up the traversal


#### Using Custom Values
```python
from compressure.main import CompressureSystem, generate_timeline_function
from compressure.dataproc import concat_videos
from copy import deepcopy

# Instantiate the controller (including persistent caching, encoding, slicing)
controller = CompressureSystem(fpath_manifest, workdir, verbosity)

# Forward and backward videos - could be different sources entirely!
fpath_source_fwd = "~/data/video/input/blooming-4.mov"
fpath_source_back = "~/data/video/input/blooming-4_reverse.mov"

# Encode both - may replace all references to "compression" with "encoding"
fpath_encode_fwd = controller.compress(
    fpath_source_fwd,
    gop_size=6000,
    encoder='libx264',
    encoder_config={
        'preset': 'veryslow',
        'qp': 31,
        'bf': 0,
    },
)
fpath_encode_back = controller.compress(
    fpath_source_back,
    gop_size=6000,
    encoder='libx264',
    encoder_config={
        'preset': 'veryslow',
        'qp': 31,
        'bf': 0,
    },
)

# Slice both into "superframes" - very short (4-10 frames) video files,
# each offset by one frame with respect to its neighbors 
dpath_slices_fwd = controller.slice(
    fpath_source=fpath_source_fwd,
    fpath_encode=fpath_encode_fwd,
    superframe_size=6,
)
dpath_slices_back = controller.slice(
    fpath_source=fpath_source_back,
    fpath_encode=fpath_encode_back,
    superframe_size=6,
)

# Create "buffer" of all superframes, for scrubbing through the timeline by superframes
buffer = controller.init_buffer(dpath_slices_fwd, dpath_slices_back, superframe_size=6)

# Generate a timeline function, establishing how we're moving through the timeline.
# TODO we want this to be controlled live, rather than a predefined function like so
timeline = generate_timeline_function(6, len(buffer), frequency=0.5, n_superframes=100)

# Now use the timeline to step through the video buffer
video_list = [deepcopy(buffer.state)]
for loc in timeline:
    video_list.append(buffer.step(to=loc))

# Finally, concatenate the videos!
concat_videos(video_list, fpath_out="~/data/video/output/output.mov")
```

This is where it starts to become an interesting experiment. We recommend playing around with this - use different presets, codecs, qp values, bitrates, superframe sizes, timeline functions, etc.!

Once we have a GUI and support live video creation, the experimentation process will be much faster!

### Command Line
```bash
python main.py \
  -f ~/data/video/input/blooming-4.mov \
  -b ~/data/video/input/blooming-4_reverse.mov \
  -g 6000 \
  --encoder libx264 \
  --encoder_config preset veryslow qp 31 bf 0 \
  --superframe_size 6 \
  --frequency 0.5 \
  --n_superframes 100 \
  -o ~/data/video/output/output.mov
```

The above will do exactly what we're doing above, from the command line. This may be the fastest way of interacting with it
