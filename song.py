#!/usr/bin/env python3

from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from collections import namedtuple
import contextlib
import distutils.util
import enum
import logging
import os
import shutil
import subprocess
import sys
from typing import Any, Iterable, Optional

import acoustid
from dotenv import load_dotenv
from fuzzywuzzy import fuzz
from mutagen.id3 import ID3, TPE1, TIT2, TALB, APIC


class AlbumType(enum.IntEnum):
    NONE = 0
    SINGLE = 50
    ALBUM = 100


class ExitCode(enum.IntEnum):
    SUCCESS = 0
    FAILURE = 1


Song = namedtuple(typename="Song", field_names=["artist", "title", "album"])
Score = namedtuple(typename="Score", field_names=["audio", "filename", "release"])
Match = namedtuple(typename="Match", field_names=["song", "score"])

load_dotenv()
ACOUSTID_APPLICATION_API_KEY = os.getenv("ACOUSTID_APPLICATION_API_KEY")
ACOUSTID_USER_API_KEY = os.getenv("ACOUSTID_USER_API_KEY")

logger = logging.getLogger(__name__)
# prevent duplicate logging messages by not propagating to the root logger (see: https://stackoverflow.com/a/44426266)
logger.propagate = False
handler = logging.StreamHandler(stream=sys.stderr)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)


def get_argument_parser() -> ArgumentParser:
    # fmt: off
    parser = ArgumentParser(description="Download and parse videos to tagged and normalized MP3 audio files", formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument("urls", metavar="URL", nargs="+", help="Video URLs, which are passed to youtube-dl for downloading")
    parser.add_argument("-od", "--output-directory", metavar="DIRECTORY", default=".", help="Custom output directory to place the resulting audio files in")
    parser.add_argument("-f", "--files", action="store_true", help="Interpret provided URLs as local MP3 files and skip downloading")
    parser.add_argument("-dd", "--download-directory", metavar="DIRECTORY", default="downloaded", help="Custom output directory to place downloaded MP3 files in (only used when -m/--mp3 is not specified)")
    parser.add_argument("-k", "--keep", action="store_true", help="Keep original MP3 files instead of overwriting them")
    parser.add_argument("-s", "--skip", action="store_true", help="Skip processing of unconfident song matches and instead place them in a seperate directory (see: -d/--skipped-directory)")
    parser.add_argument("-sd", "--skip-directory", metavar="DIRECTORY", default="skipped", help="Custom output directory to place skipped song matches in (only used in conjunction with -s/--skip)")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Set the verbosity level of the program")
    parser.add_argument("-ey", "--extra-youtube-dl", metavar="ARGUMENT", nargs="+", default=[], help="Additional arguments passed for youtube-dl invocation (arguments starting with one or more dashes need to be prepended with a space to circumvent argparse)")
    parser.add_argument("-ef", "--extra-ffmpeg-normalize", metavar="ARGUMENT", nargs="+", default=[], help="Additional arguments passed for ffmpeg-normalize invocation (arguments starting with one or more dashes need to be prepended with a space to circumvent argparse)")
    parser.add_argument("-es", "--extra-sacad", metavar="ARGUMENT", nargs="+", default=[], help="Additional arguments passed for sacad invocation (arguments starting with one or more dashes need to be prepended with a space to circumvent argparse)")
    parser.add_argument("-m", "--manual", action="store_true", help="Always query the user for manual corrections even if automatic MP3 tagging finished confidently")
    # fmt: on
    return parser


def download_mp3files(urls, download_directory, extra_args):
    process = subprocess.run(
        [
            "yt-dlp",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            *urls,
            "--output",
            os.path.join(download_directory, "%(title)s.%(ext)s"),  # set filename to video title
            # append extra arguments
            *(extra_arg.lstrip() for extra_arg in extra_args),
        ],
        # create readable unified output to aid debugging
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
        text=True,
    )
    if process.returncode != ExitCode.SUCCESS:
        logger.error(f"subprocess {process.args} failed with exit code {process.returncode}:\n{process.stdout}")
        sys.exit(ExitCode.FAILURE)

    # extract filenames of written mp3 files from output
    lines = process.stdout.splitlines()
    mp3files = [line.split(sep=" ", maxsplit=2)[-1] for line in lines if "Destination" in line and "mp3" in line]
    return mp3files


def parse_artist(artists: Iterable[Any]) -> str:
    artist_joined = ""
    for artist in artists:
        artist_joined += artist["name"]
        if "joinphrase" in artist:
            artist_joined += artist["joinphrase"]
    return artist_joined


def find_album_release(releases: Iterable[Any]) -> Optional[str]:
    for release in releases:
        # ignore compilation and mix albums by checking for secondarytypes
        if "type" in release and release["type"] == "Album" and "secondarytypes" not in release:
            return release["title"]
    return None


def find_single_release(releases: Iterable[Any]) -> Optional[str]:
    for release in releases:
        # ignore compilation and mix albums by checking for secondarytypes
        if "type" in release and release["type"] == "Single":
            return f"{release['title']} - Single"
    return None


def fingerprint_mp3file(mp3file):
    response: Any = acoustid.match(ACOUSTID_APPLICATION_API_KEY, mp3file, parse=False, meta="recordings releasegroups")
    mp3name = os.path.basename(os.path.abspath(mp3file))

    matches = [Match(Song("", "", ""), Score(0, 0, 0))]
    for result in response["results"]:
        audio_score = result["score"] * 100

        if "recordings" not in result:
            continue
        for recording in result["recordings"]:
            if "artists" not in recording:
                continue
            artist = parse_artist(recording["artists"])

            if "title" not in recording:
                continue
            title = recording["title"]

            filename_score = fuzz.token_set_ratio(mp3name, f"{artist} - {title}")

            if "releasegroups" not in recording:
                continue

            if release := find_album_release(recording["releasegroups"]):
                release_score = AlbumType.ALBUM
            elif release := find_single_release(recording["releasegroups"]):
                release_score = AlbumType.SINGLE
            else:
                # suggest single release but do not mark as single match to ask user for confirmation
                release = f"{title} - Single"
                release_score = AlbumType.NONE

            song = Song(artist, title, release)
            score = Score(audio_score, filename_score, release_score)
            matches.append(Match(song, score))

    song, score = max(matches, key=lambda match: match.score.filename * 1000 + match.score.release)
    confident = score.audio >= 40 and score.filename >= 70 and score.release > AlbumType.NONE
    return song, confident


def bool_input(prompt: str) -> bool:
    while True:
        try:
            return bool(distutils.util.strtobool(input(prompt)))
        except ValueError:
            print("Please answer y(es) or n(o)!")


def ask_user(mp3file: str, song: Song):
    print("Auto tagging finished with a low confidence level")
    print(f"Filename: {os.path.basename(mp3file)}")
    print(f"Artist: {song.artist}")
    print(f"Title: {song.title}")
    print(f"Album: {song.album}")

    if bool_input("Perform manual adjustments? "):
        print("Leave individual fields blank to keep the old value")
        artist = input("New Artist: ") or song.artist
        title = input("New Title: ") or song.title
        album = input("New Album: ") or song.album
        song = Song(artist, title, album)

        if bool_input("Submit new MP3 tags to the AcoustID web service? "):
            duration, fingerprint = acoustid.fingerprint_file(mp3file)
            mp3data = {
                "duration": duration,
                "fingerprint": fingerprint,
                "artist": artist,
                "track": title,
                "album": album,
                "albumartist": artist,
                "fileformat": "MP3",
            }
            acoustid.submit(ACOUSTID_APPLICATION_API_KEY, ACOUSTID_USER_API_KEY, mp3data)

    return song


def copy_or_move(source, destination, keep_original):
    if keep_original:
        try:
            shutil.copy2(source, destination)
        except shutil.SameFileError:
            logger.warning(
                f"although -k/--keep is specified, the mp3file {source} will be overwritten due to the output directory"
            )
    else:
        os.replace(source, destination)


def rename_mp3file(mp3file, song, output_directory, keep_original):
    os.makedirs(output_directory, exist_ok=True)
    # cannot use / directly in a filename but the unicode character for division ⧸ can be
    new_file = os.path.join(output_directory, f"{song.artist} - {song.title}.mp3".replace("/", "⧸"))
    copy_or_move(mp3file, new_file, keep_original)
    return new_file


def download_cover(artist: str, album: str, filename: str, extra_args: list[str]):
    COVER_IMAGE_SIZE = 600
    process = subprocess.run(
        [
            "sacad",
            "--verbosity",
            "quiet",
            artist,
            album,
            f"{COVER_IMAGE_SIZE}",
            filename,
            # append extra arguments
            *(extra_arg.lstrip() for extra_arg in extra_args),
        ],
        # create readable unified output to aid debugging
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
        text=True,
    )
    if process.returncode != ExitCode.SUCCESS:
        logger.error(f"subprocess {process.args} failed with exit code {process.returncode}:\n{process.stdout}")
        sys.exit(ExitCode.FAILURE)


def add_cover(audio: ID3, song: Song, extra_sacad: list[str]):
    COVER_FILENAME = "Cover.jpeg"
    download_cover(song.artist, song.album.removesuffix(" - Single"), COVER_FILENAME, extra_sacad)
    if os.path.exists(COVER_FILENAME):
        with open(COVER_FILENAME, "rb") as cover:
            audio.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover.read()))
        os.remove(COVER_FILENAME)
    else:
        logger.warning(f"could not get cover art for mp3file: {audio.filename}")


def write_mp3tags(mp3file: str, song: Song, extra_sacad: list[str]):
    audio = ID3(mp3file)
    audio.clear()
    audio.add(TPE1(encoding=3, text=song.artist))
    audio.add(TIT2(encoding=3, text=song.title))
    audio.add(TALB(encoding=3, text=song.album))
    add_cover(audio, song, extra_sacad)
    audio.save()


def normalize_mp3file(mp3file, extra_args):
    process = subprocess.run(
        [
            "ffmpeg-normalize",
            "--quiet",
            mp3file,
            # read and write an mp3 file
            "--audio-codec",
            "libmp3lame",
            # use highest quality
            "--audio-bitrate",
            "320k",
            # perform inplace normalization
            "--output",
            mp3file,
            "--force",
            # append extra arguments
            *(extra_arg.lstrip() for extra_arg in extra_args),
        ],
        # create readable unified output to aid debugging
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
        text=True,
    )
    if process.returncode != ExitCode.SUCCESS:
        logger.error(f"subprocess {process.args} failed with exit code {process.returncode}:\n{process.stdout}")
        sys.exit(ExitCode.FAILURE)


def modify_mp3file(mp3file, song, output_directory, keep_original, extra_sacad, extra_ffmpeg):
    mp3file = rename_mp3file(mp3file, song, output_directory, keep_original)
    logger.debug(f"writing mp3tags to mp3file: {song} --> {mp3file}")
    write_mp3tags(mp3file, song, extra_sacad)
    logger.debug(f"normalizing audio volume of mp3file: {mp3file}")
    normalize_mp3file(mp3file, extra_ffmpeg)
    return mp3file


def main(arguments=None):
    arguments = get_argument_parser().parse_args(args=arguments)
    logger.setLevel(logging.WARNING - arguments.verbose * 10)
    logger.debug(f"received the following arguments: {arguments}")
    mp3files = (
        download_mp3files(arguments.urls, arguments.download_directory, arguments.extra_youtube_dl)
        if not arguments.files
        else arguments.urls
    )
    logger.debug(f"all mp3files to process: {mp3files}")
    for mp3file in mp3files:
        logger.info(f"start processing mp3file: {mp3file}")
        song, confident = fingerprint_mp3file(mp3file)
        logger.debug(f"fingerprinting finished with result: {song}")
        if not confident or arguments.manual:
            logger.debug(f"low confidence for the correctness of the fingerprinting result")
            if arguments.skip:
                os.makedirs(arguments.skip_directory, exist_ok=True)
                new_file = os.path.join(arguments.skip_directory, os.path.basename(mp3file))
                copy_or_move(mp3file, new_file, arguments.keep)
                logger.info(f"skipped processing of song and place mp3file in: {new_file}")
                continue
            song = ask_user(mp3file, song)
            logger.debug(f"using user-corrected song attributes: {song}")
        mp3file = modify_mp3file(
            mp3file,
            song,
            arguments.output_directory,
            arguments.keep,
            arguments.extra_sacad,
            arguments.extra_ffmpeg_normalize,
        )
        logger.info(f"wrote result to mp3file: {mp3file}")
    try:
        os.rmdir(arguments.download_directory)
    except (FileNotFoundError, OSError):
        # directory does not exist or is not empty
        pass


if __name__ == "__main__":
    main()
