#!/usr/bin/env python3

import collections
import contextlib
import io
import logging
import os
import sys
import urllib.request

import acoustid
import dotenv
import ffmpeg_normalize
from ffmpeg_normalize.__main__ import main as ffmpeg_normalize_main
from fuzzywuzzy import fuzz, process
from google_images_download import google_images_download
from mutagen.id3 import ID3, TPE1, TIT2, TALB, APIC
import youtube_dl

Song = collections.namedtuple(typename='Song', field_names=['artist', 'title', 'album'])

dotenv.load_dotenv()
ACOUSTID_API_KEY = os.getenv("ACOUSTID_API_KEY")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(stream=sys.stderr)
formatter = logging.Formatter('%(asctime)s:%(name)s:%(levelname)s:%(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

@contextlib.contextmanager
def main_arguments(argv=None):
    sys._argv = sys.argv[:]
    sys.argv = argv
    yield
    sys.argv = sys._argv

def download_mp3file(url):
	output = io.StringIO()
	with contextlib.redirect_stdout(output):
		try:
			youtube_dl.main(argv=[
				'--extract-audio', '--audio-format', 'mp3', '--audio-quality', '0', # store best audio as mp3
				url, '--output', '%(title)s.%(ext)s', # set filename to video title
			])
		except SystemExit:
			# prevent youtube_dl's sys.exit call from stopping execution
			pass
	
	# extract filename of written mp3 from youtube_dl output
	lines = output.getvalue().splitlines()
	line = [line for line in lines if 'Destination' in line][-1]
	mp3file = ' '.join(line.split()[2:])
	return mp3file

def parse_artist(json):
	artist_joined = ''
	for artist in json['artists']:
		artist_joined += artist['name']
		if 'joinphrase' in artist:
			artist_joined += artist['joinphrase']
	return artist_joined

def fingerprint_mp3file(mp3file):
	response = acoustid.match(ACOUSTID_API_KEY, mp3file, parse=False, meta='recordings releasegroups')

	matches = {}
	for result in response['results']:
		if 'recordings' not in result:
			continue
		for recording in result['recordings']:
			if 'artists' not in recording:
				continue
			artist = parse_artist(recording)

			if 'title' not in recording:
				continue
			title = recording['title']

			album = None
			if 'releasegroups' in recording:
				for releasegroup in recording['releasegroups']:
					album_artist = parse_artist(releasegroup)

					if album_artist == artist:
						# TODO: change handling of Singles and Albums as well as suboptimal albums, e.g. use score
						# - different artist: 25
						# - compilation: 50
						# - single: 75
						# - album: 100
						# TODO: prevent None album values due to mp3tagging error
						# ignore compilations
						if 'secondarytypes' in releasegroup:
							continue
						# prefer entries of type album over everything
						if releasegroup['type'] == 'Album':
							album = releasegroup['title']
							break
						# if we do not find any entry of type album, settle for an entry of type single
						if not album and releasegroup['type'] == 'Single':
							album = releasegroup['title']

			matches[Song(artist, title, album)] = result['score'] * 100
	if not matches:
		return Song(None, None, None), False

	mp3name = os.path.basename(os.path.abspath(mp3file))
	song, filename_score = process.extractOne(
		mp3name, choices=list(matches.keys()),
		processor=lambda song: f'{song.artist} - {song.title}' if type(song) != str else song,
		scorer=fuzz.token_set_ratio
	)
	mp3audio_score = matches[song]
	confident = filename_score >= 70 or mp3audio_score >= 40
	
	return song, confident

def ask_user(mp3file, song):
	print('Auto tagging finished with a low confidence level')
	print(f'Filename: {mp3file}')
	print(f'Artist: {song.artist}')
	print(f'Title: {song.title}')
	print(f'Album: {song.album}')

	answer = input('Perform manual adjustments? ')
	if 'n' in answer or 'N' in answer:
		return song

	artist = input('New Artist: ')
	title = input('New Title: ')
	album = input('New Album: ')
	return Song(artist, title, album)

def rename_mp3file(mp3file, song):
	new_file = f'{song.artist} - {song.title}.mp3'
	os.rename(mp3file, os.path.join(os.path.dirname(mp3file), new_file))
	return new_file

def write_mp3tags(mp3file, song):
	arguments = {
		'keywords': f'{song.artist} {song.title} Album Cover',
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
	with urllib.request.urlopen(paths[arguments['keywords']][0]) as cover:
		audio['APIC'] = APIC(encoding=3, mime=cover.info().get_content_type(), type=3, desc='Cover', data=cover.read())
	audio.save()

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

def main(argv=None):
	if len(argv) < 2:
		logger.error('please provide a youtube video url')
		sys.exit(1)
	url = argv[1]

	mp3file = download_mp3file(url)
	song, confident = fingerprint_mp3file(mp3file)
	if not confident:
		song = ask_user(mp3file, song)
	modify_mp3file(mp3file, song)

if __name__ == '__main__':
	main(argv=sys.argv)

