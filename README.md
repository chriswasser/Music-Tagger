# Music-Tagger

A Python script for automatic downloading and parsing of videos to tagged and normalized MP3 audio files

## Installation

- The currently supported Python version can be found in `version.txt`.
- The current package dependencies can be found in `requirements.txt`.

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
