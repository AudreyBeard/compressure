FNAME_VIDEO_FORWARD="video_1.mp4"
FNAME_VIDEO_BACKWARD="video_2.mov"

python3 compressure/main.py \
    --fpath_manifest /output/.cache/compressure/manifest.json \
    --dpath_workdir /output/.cache/compressure/ \
    -f /input/$FNAME_VIDEO_FORWARD \
    -b /input/$FNAME_VIDEO_BACKWARD \
    --scaled \
    --frequency 1 \
    --superframe_size 6 \
    --n_superframes 500 \
    -o /output/output.mov
