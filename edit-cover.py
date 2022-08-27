import collections
import sys
import urllib.request
import urllib.error

from mutagen.id3 import ID3, TPE1, TIT2, TALB, APIC

Song = collections.namedtuple(typename="Song", field_names=["artist", "title", "album"])

mp3 = sys.argv[1]
url = sys.argv[2]

audio = ID3(mp3)
song = Song(
    artist=audio.getall("TPE1")[0].text[0],
    title=audio.getall("TIT2")[0].text[0],
    album=audio.getall("TALB")[0].text[0],
)
audio.clear()
audio.add(TPE1(encoding=3, text=song.artist))
audio.add(TIT2(encoding=3, text=song.title))
audio.add(TALB(encoding=3, text=song.album))
try:
    with urllib.request.urlopen(url) as cover:
        content_type = cover.info().get_content_type()
        audio.add(APIC(encoding=3, mime=content_type, type=3, desc="Cover", data=cover.read()))
except urllib.error.HTTPError as error:
    print(f"cover download failed and returned HTTP error code {error.code} with reason: {error.reason}")
audio.save()
