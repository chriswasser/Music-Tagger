#!/usr/bin/env python3

from __future__ import annotations

from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from dataclasses import dataclass
import distutils.util
from enum import Enum, IntEnum, auto
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


class ExitCode(IntEnum):
    SUCCESS = 0
    FAILURE = 1


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
    parser.add_argument("-od", "--output-directory", metavar="DIRECTORY", default="finished", help="Custom output directory to place the resulting audio files in")
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


class AcoustidReleaseType(Enum):
    SINGLE = auto()
    ALBUM = auto()
    OTHER = auto()

    @staticmethod
    def get(key: str, default: AcoustidReleaseType) -> AcoustidReleaseType:
        try:
            return AcoustidReleaseType[key]
        except KeyError:
            return default


class ReleaseTypeScore(IntEnum):
    ALBUM = 10
    SINGLE = 5
    OTHER = 0


def parse_types(type: str, secondarytypes: list[str]) -> list[AcoustidReleaseType]:
    return [AcoustidReleaseType.get(type.upper(), AcoustidReleaseType.OTHER)] + [
        AcoustidReleaseType.get(secondarytype.upper(), AcoustidReleaseType.OTHER) for secondarytype in secondarytypes
    ]


@dataclass
class AcoustidRelease:
    artist: str
    title: str
    types: list[AcoustidReleaseType]

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> AcoustidRelease:
        return cls(
            artist=parse_artist(json.get("artists", [])),
            title=json.get("title", ""),
            types=parse_types(json.get("type", ""), json.get("secondarytypes", [])),
        )


@dataclass
class AcoustidRecording:
    artist: str
    title: str
    releases: list[AcoustidRelease]

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> AcoustidRecording:
        return cls(
            artist=parse_artist(json.get("artists", [])),
            title=json.get("title", ""),
            releases=[AcoustidRelease.from_json(release) for release in json.get("releasegroups", [])],
        )


@dataclass
class AcoustidResult:
    score: float
    recordings: list[AcoustidRecording]

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> AcoustidResult:
        return cls(
            score=json.get("score", 0.0),
            recordings=[AcoustidRecording.from_json(recording) for recording in json.get("recordings", [])],
        )


@dataclass
class Score:
    audio: float
    file: int
    type: ReleaseTypeScore


@dataclass
class Song:
    artist: str
    title: str
    album: str


@dataclass
class Match:
    song: Song
    score: Score

    def is_confident(self) -> bool:
        return self.score.audio >= 0.40 and self.score.file >= 70 and self.score.type >= ReleaseTypeScore.SINGLE


def find_album(releases: list[AcoustidRelease]) -> Optional[AcoustidRelease]:
    for release in releases:
        if len(release.types) == 1 and release.types[0] == AcoustidReleaseType.ALBUM:
            return release
    return None


def find_single(releases: list[AcoustidRelease]) -> Optional[AcoustidRelease]:
    for release in releases:
        if len(release.types) == 1 and release.types[0] == AcoustidReleaseType.SINGLE:
            return release
    return None


def find_best_match(results: list[AcoustidResult], mp3basename: str) -> Match:
    matches = [Match(Song("", "", ""), Score(0.0, 0, ReleaseTypeScore.OTHER))]
    for result in results:
        for recording in result.recordings:
            file_score = score_recording_for_file(recording, mp3basename)

            release = (
                find_album(recording.releases)
                or find_single(recording.releases)
                or AcoustidRelease("", f"{recording.title} - Single", [AcoustidReleaseType.OTHER])
            )

            song = Song(recording.artist, recording.title, release.title)
            score = Score(
                audio=result.score,
                file=file_score,
                type=ReleaseTypeScore[release.types[0].name],
            )
            matches.append(Match(song=song, score=score))

    return max(matches, key=lambda match: match.score.file * 1000 + match.score.type)


def score_recording_for_file(recording: AcoustidRecording, basename: str) -> int:
    return fuzz.token_set_ratio(f"{recording.artist} - {recording.title}", basename)


def fingerprint_mp3file(mp3file):
    response: Any = acoustid.match(ACOUSTID_APPLICATION_API_KEY, mp3file, parse=False, meta="recordings releasegroups")
    results = [AcoustidResult.from_json(result) for result in response["results"]]
    results = [result for result in results if len(result.recordings) > 0]
    match = find_best_match(results, os.path.basename(mp3file))
    print(mp3file, match)
    return match.song, match.is_confident()


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
        arguments.urls
        if arguments.files
        else download_mp3files(arguments.urls, arguments.download_directory, arguments.extra_youtube_dl)
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
            else:
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
