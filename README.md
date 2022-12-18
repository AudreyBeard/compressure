[[_TOC_]]

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
