FROM jrottenberg/ffmpeg:4.1-ubuntu
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /compressure
COPY .. .
RUN apt-get update; \
    apt-get install -y \
    python3.9 \
    python3-pip


RUN pip install -r requirements.txt; \
    pip install .
