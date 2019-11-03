#!/usr/bin/env python3

import os
import sys

import acoustid
from fuzzywuzzy import fuzz, process
from dotenv import load_dotenv

load_dotenv()
ACOUSTID_API_KEY = os.getenv("ACOUSTID_API_KEY")

mp3file = sys.argv[1]
if not os.path.isfile(mp3file):
	print(f'ERROR: the mp3 audio file "{mp3file}" does not exist')
	sys.exit(1)

response = acoustid.match(ACOUSTID_API_KEY, mp3file, parse=False)

matches = {}
for result in response['results']:
	if 'recordings' not in result:
		continue
	for recording in result['recordings']:
		if 'title' not in recording:
			continue
		title = recording['title']

		if 'artists' not in recording:
			continue
		joined_artists = ''
		for artist in recording['artists']:
			joined_artists += artist['name']
			if 'joinphrase' in artist:
				joined_artists += artist['joinphrase']

		matches[f'{joined_artists} - {title}'] = result['score'] * 100
if not matches:
	print(f'ERROR: cannot find any matches based on the acoustid fingerprint of "{mp3file}"')
	sys.exit(1)

mp3name = os.path.basename(os.path.abspath(mp3file))
best_match, filename_score = process.extractOne(mp3name, choices=list(matches.keys()), scorer=fuzz.token_set_ratio)
mp3audio_score = matches[best_match]

print(f'{mp3name}')
print(f'--> {best_match}')
print(f'--> filename_score: {filename_score}')
print(f'--> mp3audio_score: {mp3audio_score}')
if filename_score < 70 or mp3audio_score < 40:
	print('WARNING: low confidence level for tagging')

