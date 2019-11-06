#!/usr/bin/env python3

import os
import sys
import urllib.request

from mutagen.id3 import ID3, TPE1, TIT2, TALB, APIC

filename = sys.argv[1]
artist = sys.argv[2]
title = sys.argv[3]
album = sys.argv[4]
url = sys.argv[5]

audio = ID3(filename)
audio['TPE1'] = TPE1(encoding=3, text=artist)
audio['TIT2'] = TIT2(encoding=3, text=title)
audio['TALB'] = TALB(encoding=3, text=album)
with urllib.request.urlopen(url) as cover:
	audio['APIC'] = APIC(encoding=3, mime=cover.info().get_content_type(), type=3, desc='Cover', data=cover.read())
audio.save()

