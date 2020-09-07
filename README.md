# Music-Tagger

A Python script for automatic downloading and parsing of videos to tagged and normalized MP3 audio files

## Installation

- The currently supported Python version can be found in `.python-version`.
- The current package dependencies can be found in `requirements.txt`.
- The used [`ffmpeg-normalize`](https://github.com/slhck/ffmpeg-normalize "Github ffmpeg-normalize") package requires [FFmpeg](https://ffmpeg.org "FFmpeg homepage"). See installation instructions on either webpage.
- The used [`pyacoustid`](https://github.com/beetbox/pyacoustid "Github pyacoustid") package requires the [Chromaprint](https://github.com/acoustid/chromaprint "Github chromaprint") fingerprinting library. See installation instructions on either webpage.
- The used [`sacad`](https://github.com/desbma/sacad "Github SACAD") package optionally uses [optipng](http://optipng.sourceforge.net/ "Sourceforge optipng") and [jpegoptim](http://freecode.com/projects/jpegoptim "Sourceforge jpegoptim") to benefit from smaller cover images by applying lossless recompression.

```sh
$ git clone git@github.com:chriswasser/Music-Tagger.git
# clone the repository
$ cd Music-Tagger
# change into the created directory
$ python3 -m venv venv
# create a new python3 virtual environment
$ . venv/bin/activate
# activate the virtual environment
$ pip install --requirement requirements.txt
# install the required package dependencies
$ python3 song.py --help
# print an up-to-date help message
```

## Setup

The fingerprinting capabilities of the script are provided by the [AcoustID web service](https://acoustid.org/webservice "AcoustID web service").
Using its API requires an API key, which can be generated for free when registering your application.
In order to submit new fingerprints, your user specific API key needs to be provided as well.
Both of these can be stored in a [dotenv](https://github.com/theskumar/python-dotenv "Github python-dotenv") file called `.env`.
The settings will be loaded automatically during script execution and may look something like below.

```sh
$ cat .env
ACOUSTID_APPLICATION_API_KEY=XXXXXXXXXX
ACOUSTID_USER_API_KEY=YYYYYYYYYY
```

## Usage

- An up-to-date help message will be printed when executing `python3 song.py --help`
