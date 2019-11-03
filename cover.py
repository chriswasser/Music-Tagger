#!/usr/bin/env python3

import os
import sys

from dotenv import load_dotenv
from google_images_search import GoogleImagesSearch

load_dotenv()
GOOGLE_PROJECT_BASED_API_KEY = os.getenv('GOOGLE_PROJECT_BASED_API_KEY')
GOOGLE_CUSTOM_SEARCH_ENGINE_ID = os.getenv('GOOGLE_CUSTOM_SEARCH_ENGINE_ID')

query = sys.argv[1]

google_images = GoogleImagesSearch(GOOGLE_PROJECT_BASED_API_KEY, GOOGLE_CUSTOM_SEARCH_ENGINE_ID)

parameters = {
	'q': query,
	'num': 10,
}
google_images.search(search_params=parameters)

for num, image in enumerate(google_images.results()):
	image.download('covers')
	
	old_path = os.path.abspath(image.path)
	new_path = os.path.join(os.path.dirname(old_path), f'cover-{num}{os.path.splitext(old_path)[1]}')
	os.rename(old_path, new_path)

	print(f'cover {num}')
	print(f'--> {new_path}')
	print(f'--> {image.url}')

