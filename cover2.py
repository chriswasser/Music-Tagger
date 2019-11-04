#!/usr/bin/env python3

import os
import sys

from google_images_download import google_images_download

response = google_images_download.googleimagesdownload()

arguments = {
	'keywords': sys.argv[1],
	'limit': 10,
	'output_directory': 'covers',
	'no_directory': True,
}
paths, num_errors = response.download(arguments)

if num_errors > 0:
	print(f'WARNING: during cover download {num_errors} errors occurred')

for num, image in enumerate(list(paths.values())[0]):
	old_path = os.path.abspath(image)
	new_path = os.path.join(os.path.dirname(old_path), f'cover-{num}{os.path.splitext(old_path)[1]}')
	os.rename(old_path, new_path)

	print(f'cover {num}')
	print(f'--> {new_path}')

