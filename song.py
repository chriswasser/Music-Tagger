#!/usr/bin/env python3

import collections
import contextlib
import io
import sys

import ffmpeg_normalize
import youtube_dl

Song = collections.namedtuple(typename='Song', field_names=['artist', 'title', 'album'])

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
				'--output', '%(title)s.%(ext)s', url, # set filename to video title
			])
		except SystemExit:
			# prevent youtube_dl's sys.exit call from stopping execution
			pass
	
	# extract filename of written mp3 from youtube_dl output
	lines = output.getvalue().splitlines()
	line = [line for line in lines if 'Destination' in line][-1]
	mp3file = ' '.join(line.split()[2:])
	return mp3file

def fingerprint_mp3file(mp3file):
	pass

def ask_user(mp3file, song):
	pass

def rename_mp3file(mp3file, song):
	pass

def write_mp3tags(mp3file, song):
	pass

def normalize_mp3file(mp3file):
	# pass custom arguments to ffmpeg_normalize's main
	with main_arguments(argv=[
			'-c:a', 'libmp3lame', '-b:a', '320k', # read and write an mp3file
			'-f', '-o', mp3file, mp3file, # perform inplace normalization
		]):
		ffmpeg_normalize.main()

def modify_mp3file(mp3file, song):
	mp3file = rename_mp3file(mp3file, song)
	write_mp3tags(mp3file, song)
	normalize_mp3file(mp3file)

def main(argv=None):
	if len(argv) < 2:
		print('ERROR: please provide a youtube video url')
		sys.exit(1)
	url = argv[1]

	mp3file = download_mp3file(url)
	song, confident = fingerprint_mp3file(mp3file)
	if not confident:
		song = ask_user(mp3file, song)
	modify_mp3file(mp3file, song)

if __name__ == '__main__':
	main(argv=sys.argv)

