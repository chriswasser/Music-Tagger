#!/usr/bin/env zsh

input="${1}"
output="${2}"

ffmpeg-normalize -c:a libmp3lame -b:a 320k "${input}" -o "${output}"

