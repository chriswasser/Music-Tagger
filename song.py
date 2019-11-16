#!/usr/bin/env python3

import argparse
import collections
import contextlib
from distutils.util import strtobool
from enum import IntEnum
import io
import logging
import os
import sys
import urllib.request

import acoustid
import dotenv
import ffmpeg_normalize
from ffmpeg_normalize.__main__ import main as ffmpeg_normalize_main
from fuzzywuzzy import fuzz
from google_images_download import google_images_download
from mutagen.id3 import ID3, TPE1, TIT2, TALB, APIC
import youtube_dl

Song = collections.namedtuple(typename='Song', field_names=['artist', 'title', 'album'])
Score = collections.namedtuple(typename='Score', field_names=['audio', 'filename', 'album'])
Match = collections.namedtuple(typename='Match', field_names=['song', 'score'])

class AlbumType(IntEnum):
	NONE = 0
	MIX = 25
	COMPILATION = 50
	SINGLE = 75
	ALBUM = 100

dotenv.load_dotenv()
ACOUSTID_APPLICATION_API_KEY = os.getenv("ACOUSTID_APPLICATION_API_KEY")
ACOUSTID_USER_API_KEY = os.getenv("ACOUSTID_USER_API_KEY")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(stream=sys.stderr)
formatter = logging.Formatter('%(asctime)s:%(name)s:%(levelname)s:%(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

def get_argument_parser():
	parser = argparse.ArgumentParser(description='Download and parse YouTube videos into tagged and normalized MP3 audio files')
	parser.add_argument('urls', metavar='URL', nargs='+', help='Video URLs, which are passed to youtube-dl for downloading')
	parser.add_argument('-m', '--mp3', action='store_true', help='Interpret provided URLs as local MP3 files and skip downloading')
	return parser

def download_mp3files(urls):
	output = io.StringIO()
	with contextlib.redirect_stdout(output):
		try:
			youtube_dl.main(argv=[
				'--extract-audio', '--audio-format', 'mp3', '--audio-quality', '0', # store best audio as mp3
				*urls, '--output', '%(title)s.%(ext)s', # set filename to video title
			])
		except SystemExit:
			# prevent youtube_dl's sys.exit call from stopping execution
			pass

	# extract filename of written mp3 from youtube_dl output
	lines = output.getvalue().splitlines()
	mp3lines = filter(lambda line: 'Destination' in line and 'mp3' in line, lines)
	mp3files = map(lambda mp3line: ' '.join(mp3line.split()[2:]), mp3lines)
	return mp3files

def parse_artist(json):
	artist_joined = ''
	for artist in json['artists']:
		artist_joined += artist['name']
		if 'joinphrase' in artist:
			artist_joined += artist['joinphrase']
	return artist_joined

def fingerprint_mp3file(mp3file):
	response = acoustid.match(ACOUSTID_APPLICATION_API_KEY, mp3file, parse=False, meta='recordings releasegroups')
	mp3name = os.path.basename(os.path.abspath(mp3file))

	matches = [Match(Song('', '', ''), Score(0, 0, 0))]
	for result in response['results']:
		audio_score = result['score'] * 100

		if 'recordings' not in result:
			continue
		for recording in result['recordings']:
			if 'artists' not in recording:
				continue
			artist = parse_artist(recording)

			if 'title' not in recording:
				continue
			title = recording['title']

			filename_score = fuzz.token_set_ratio(mp3name, f'{artist} - {title}')

			album, album_score = '', AlbumType.NONE
			if 'releasegroups' in recording:
				for release in recording['releasegroups']:
					same_artist = parse_artist(release) == artist

					if 'type' not in release:
						continue
					is_mix = not same_artist and release['type'] == 'Album'
					is_compilation = same_artist and release['type'] == 'Album'
					is_single = same_artist and release['type'] == 'Single'
					is_album = same_artist and release['type'] == 'Album' and 'secondarytypes' not in release

					if album_score < AlbumType.MIX and is_mix:
						album, album_score = release['title'], AlbumType.MIX
					if album_score < AlbumType.COMPILATION and is_compilation:
						album, album_score = release['title'], AlbumType.COMPILATION
					if album_score < AlbumType.SINGLE and is_single:
						album, album_score = release['title'] + ' - Single', AlbumType.SINGLE
					if album_score < AlbumType.ALBUM and is_album:
						album, album_score = release['title'], AlbumType.ALBUM

			song = Song(artist, title, album)
			score = Score(audio_score, filename_score, album_score)
			matches.append(Match(song, score))
	
	song, score = max(matches, key=lambda match: match.score.filename * 1000 + match.score.album)
	confident = score.audio >= 40 and score.filename >= 70 and score.album >= AlbumType.SINGLE
	return song, confident

def bool_input(prompt):
	while True:
		try:
			return bool(strtobool(input(prompt)))
		except ValueError:
			print('Please answer y(es) or n(o)!')

def ask_user(mp3file, song):
	print('Auto tagging finished with a low confidence level')
	print(f'Filename: {mp3file}')
	print(f'Artist: {song.artist}')
	print(f'Title: {song.title}')
	print(f'Album: {song.album}')

	adjust_manually = bool_input('Perform manual adjustments? ')
	if adjust_manually:
		print('Leave individual fields blank to keep the old value')
		artist = input('New Artist: ') or song.artist
		title = input('New Title: ') or song.title
		album = input('New Album: ') or song.album
		song = Song(artist, title, album)

	submit_mp3tags = bool_input('Submit MP3 tags to the AcoustID web service? ')
	if submit_mp3tags:
		duration, fingerprint = acoustid.fingerprint_file(mp3file)
		mp3data = {
			'duration': duration,
			'fingerprint': fingerprint,
			'artist': artist,
			'track': title,
			'album': album,
			'albumartist': artist,
			'fileformat': 'MP3',
		}
		acoustid.submit(ACOUSTID_APPLICATION_API_KEY, ACOUSTID_USER_API_KEY, mp3data)

	return song

def rename_mp3file(mp3file, song):
	new_file = f'{song.artist} - {song.title}.mp3'
	os.rename(mp3file, os.path.join(os.path.dirname(mp3file), new_file))
	return new_file

def write_mp3tags(mp3file, song):
	arguments = {
		'keywords': f'{song.artist} {song.title} {song.album} Cover'.replace(',', ''),
		'limit': 1,
		'no_download': True,
		'silent_mode': True,
	}
	while True:
		with contextlib.redirect_stdout(None):
			paths, num_errors = google_images_download.googleimagesdownload().download(arguments)
		try:
			url = paths[arguments['keywords']][0]
		except IndexError:
			logger.warning('retrying cover download due to a missing image url')
		else:
			break
	if num_errors > 0:
		logger.warning(f'during cover download {num_errors} errors occurred')

	audio = ID3(mp3file)
	audio['TPE1'] = TPE1(encoding=3, text=song.artist)
	audio['TIT2'] = TIT2(encoding=3, text=song.title)
	audio['TALB'] = TALB(encoding=3, text=song.album)
	with urllib.request.urlopen(url) as cover:
		content_type = cover.info().get_content_type()
		# pjpeg mime cannot be used for a cover
		content_type = content_type.replace('pjpeg', 'jpeg')
		audio['APIC'] = APIC(encoding=3, mime=content_type, type=3, desc='Cover', data=cover.read())
	audio.save()

@contextlib.contextmanager
def main_arguments(argv=None):
    sys._argv = sys.argv[:]
    sys.argv = argv
    yield
    sys.argv = sys._argv

def normalize_mp3file(mp3file):
	# pass custom arguments to ffmpeg_normalize's main
	with main_arguments(argv=[
			'ffmpeg-normalize', # first argument is always the program name
			'--audio-codec', 'libmp3lame', '--audio-bitrate', '320k', # read and write an mp3file
			mp3file, '--force', '--output', mp3file, # perform inplace normalization
		]):
		ffmpeg_normalize_main()

def modify_mp3file(mp3file, song):
	mp3file = rename_mp3file(mp3file, song)
	write_mp3tags(mp3file, song)
	normalize_mp3file(mp3file)

def main(arguments=None):
	arguments = get_argument_parser().parse_args(args=arguments)
	mp3files = download_mp3files(arguments.urls) if not arguments.mp3 else arguments.urls
	for mp3file in mp3files:
		song, confident = fingerprint_mp3file(mp3file)
		if not confident:
			song = ask_user(mp3file, song)
		modify_mp3file(mp3file, song)

if __name__ == '__main__':
	main()

