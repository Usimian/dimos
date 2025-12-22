#!/bin/bash
# Replace TARGET_IP with the IP address of the machine running gstreamer.sh
TARGET_IP="${1:-localhost}"  # First argument or default to localhost
ffmpeg -re -i ~/coding/dimensional/dimos/data/audio_bender/out_of_date.wav -c:a libopus -b:a 128k -f rtp rtp://10.0.0.191:5002
