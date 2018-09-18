#!/usr/bin/env python3
import requests
import cachecontrol
from flask import Flask, request
import copy
from secret import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
import boto3
import os
import json
import datetime
import gzip
import logging
import sys
import time


ACCESS_TOKEN_KEY = 'access-token.json'

SCOPES = 'playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private streaming user-follow-modify user-follow-read user-library-read user-library-modify user-read-private user-read-birthdate user-read-email user-top-read user-read-recently-played user-read-playback-state'

URLS = {
    'token': 'https://accounts.spotify.com/api/token',
    'recently_played': 'https://api.spotify.com/v1/me/player/recently-played',
    'list_playlists': 'https://api.spotify.com/v1/me/playlists',
    'playlist': 'https://api.spotify.com/v1/users/{user_id}/playlists/{playlist_id}',
    'me': 'https://api.spotify.com/v1/me',
    'devices': 'https://api.spotify.com/v1/me/player/devices',
    'top': 'https://api.spotify.com/v1/me/top/{type}',
    'followed_artists': 'https://api.spotify.com/v1/me/following?type=artist',
    'saved_albums': 'https://api.spotify.com/v1/me/albums',
    'saved_tracks': 'https://api.spotify.com/v1/me/tracks',
    'current_track': 'https://api.spotify.com/v1/me/player/currently-playing',
    'add_track': 'https://api.spotify.com/v1/playlists/{playlist_id}/tracks',
    'remove_track': 'https://api.spotify.com/v1/playlists/{playlist_id}/tracks'
}


LOG = logging.getLogger('spotifyapi')


class Puller:
    def __init__(self, verbose=True):
        self.verbose=verbose
        if verbose:
            LOG.setLevel(logging.DEBUG)
        self.sess = cachecontrol.CacheControl(requests.Session())
        self.auth = (CLIENT_ID, CLIENT_SECRET)
        self.access_token = self._refresh_token()
        self.auth_headers = {"Authorization": "Bearer " + self.access_token}

    def _log(self, msg):
        if self.verbose:
            LOG.info(msg)

    def _refresh_token(self):
        data = {
                'grant_type': 'refresh_token',
                'refresh_token': REFRESH_TOKEN
        }
        r = self.sess.post(URLS['token'], auth=self.auth, data=data)
        # self._log('refreshing token')
        token = r.json()['access_token']
        self._log('new token: {}'.format(token))
        return token

    def _rate_limit_check(self, response):
        """Checks the response header, if necessary waits what Spotify requires

        :param response: the requests response object
        :returns: True if the request needs to be resent
        :rtype: bool

        """
        code = response.status_code
        if code == 429:
            t = r.header.get('Retry-After')
            self._log('Received Retry-After {} Seconds Header'.format(t))
            time.sleep(int(t))
            return True
        elif code in [200, 201]:
            return False
        elif code in [400, 403]:
            LOG.error('returned status code {}'.format(code))
            print(response.text)
            exit()
        else:
            LOG.warning('returned status code {}, trying again in 5 seconds'
                    .format(code))
            time.sleep(5)
            return True

    def get_top(self, type_, time_range):
        """gets the top artist or tracks

        :param type_: {'artists', 'tracks'}, required
        :param time_range: {'long_term', 'medium_term', 'short_term'}, required
        :returns: json response
        :rtype: dict or list

        """
        payload = {
            "limit": 50,
            "time_range": time_range
        }
        url = URLS['top'].format(type=type_)
        self._log('fetching {} ({})'.format(url, time_range))
        r = self.sess.get(url, params=payload, headers=self.auth_headers)
        if self._rate_limit_check(r):
            return self.get_tops(type_, time_range)
        return r.json()

    def get_devices(self):
        self._log('fetching devices')
        r = self.sess.get(URLS['devices'], headers=self.auth_headers)
        if self._rate_limit_check(r):
            return self.get_devices()
        return r.json()

    def _iterate_paging_object(self, first_page):
        """returns all items in a paging object

        :param first_page: dict with keys 'items' and 'next'
        :returns: list of items, starting with those in first_page
        :rtype: list

        """
        page = first_page
        items = page['items']
        while page['next']:
            self._log('paging')
            while True:
                r = self.sess.get(page['next'], headers=self.auth_headers)
                if self._rate_limit_check(r):
                    continue
                break
            page = r.json()
            items += page['items']
        return items

    def _get_a_playlist(self, user_id, playlist_id):
        url = URLS['playlist'].format(user_id=user_id, playlist_id=playlist_id)
        self._log('fetching playlist {}'.format(url))
        r = self.sess.get(url, headers=self.auth_headers)
        if self._rate_limit_check(r):
            return self._get_a_playlist(user_id, playlist_id)
        j = r.json()
        tracks = self._iterate_paging_object(j['tracks'])
        j['tracks'] = tracks
        return j

    def get_playlists_short(self):
        """gets a user's list of playlists but not their tracks"""
        payload = {'limit': 50}
        self._log('fetching list of playlists')
        r = self.sess.get(URLS['list_playlists'],
                          params=payload, headers=self.auth_headers)
        if self._rate_limit_check(r):
            return self.get_playlists()
        j = r.json()
        return list(self._iterate_paging_object(j))

    def get_playlists(self):
        """gets user's list of playlists and their tracks

        Replaces the list of simple playlist with a list of full playlists, and
        replaces each full playlist's tracks field with a full list of tracks
        by unwrapping it from the paging object after fetching all pages. This
        returned object is not wrapped in a paging object.

        :returns: List of playlists (dict)
        :rtype: list

        """
        def get_full_playlist(playlist): 
            return self._get_a_playlist(playlist['owner']['id'],playlist['id'])

        return [get_full_playlist(p) for p in self.get_playlists_short()]

    def _get_simple_endpoint(self, url):
        self._log('fetching {}'.format(url))
        payload = {"limit": 50}
        r = self.sess.get(url, params=payload, headers=self.auth_headers)
        if self._rate_limit_check(r):
            return self._get_simple_endpoint(url)
        return (r.json())

    def get_recently_played(self):
        url = URLS['recently_played']
        self._get_simple_endpoint(url)

    def get_followed_artists(self):
        self._get_simple_endpoint(URLS['followed_artists'])

    def get_saved_albums(self):
        self._get_simple_endpoint(URLS['saved_albums'])

    def get_saved_tracks(self):
        self._get_simple_endpoint(URLS['saved_tracks'])

    def get_current_track(self):
        url = URLS['current_track']
        self._log('fetching {}'.format(url))
        r = self.sess.get(url, params=None, headers=self.auth_headers)
        if self._rate_limit_check(r):
            return self.get_current_track()
        return r.json()

    def remove_track(self, playlist_id, track_uri):
        payload = {
            "tracks": [{'uri': track_uri}]
        }
        url = URLS['remove_track'].format(playlist_id=playlist_id)
        self._log('removing {} from {}'.format(track_uri, url))
        r = self.sess.delete(url, data=json.dumps(payload), headers=self.auth_headers)
        if self._rate_limit_check(r):
            return self.remove_track(playlist_id, track_uri)
        return r.json()

    def add_track(self, playlist_id, track_uri):
        payload = {
            "uris": [track_uri]
        }
        url = URLS['add_track'].format(playlist_id=playlist_id)
        self._log('adding {} to {}'.format(track_uri, url))
        r = self.sess.post(url, params=payload, headers=self.auth_headers)
        if self._rate_limit_check(r):
            return self.add_track(playlist_id, track_uri)
        return r.json()

def put_file(content):
    LOG.info('uploading')
    utc_datetime = datetime.datetime.utcnow()
    key_name = utc_datetime.strftime("%Y-%m-%d_%H%M%S_UTC.json.gz")

    stage = os.environ.get('STAGE', 'dev')
    bucket_name = 'spotifyapi-' + stage

    LOG.info('uploading to {} : {}'.format(bucket_name, key_name))
    s3 = boto3.resource('s3')
    object = s3.Object(bucket_name, key_name)
    object.put(Body=content)


def general_setup():
    for l in ['botocore', 'boto3', 'requests', 'cachecontrol']:
        logging.getLogger(l).setLevel(logging.WARN)

def pull():
    p = Puller()
    data = {
        'playlists': p.get_playlists(),
        'recently_played': p.get_recently_played(),
        'devices': p.get_devices(),
        'top_artists_short': p.get_top('artists', 'short_term'),
        'top_artists_medium': p.get_top('artists', 'medium_term'),
        'top_artists_long': p.get_top('artists', 'long_term'),
        'top_tracks_short': p.get_top('tracks', 'short_term'),
        'top_tracks_medium': p.get_top('tracks', 'medium_term'),
        'top_tracks_long': p.get_top('tracks', 'long_term'),
        'followed_artists': p.get_followed_artists(),
        'saved_albums': p.get_saved_albums(),
        'saved_tracks': p.get_saved_tracks()
    }
    data_bytes = json.dumps(data).encode('utf-8')
    compressed = gzip.compress(data_bytes)
    put_file(compressed)


def pull_handler(event, context):
    pull()

def move_current_song(target_playlist, add=False):
    """if target_playlist is none then deletes it"""
    if target_playlist:
        target_playlist = target_playlist.lower()
    def uri_to_id(uri):
        return uri.split(':')[-1]

    p = Puller()
    r = p.get_current_track()
    if r['item']:
        track_name = r['item']['name']
        track = r['item']['uri']
    else:
        return 'Nothing is playing'
    if r['context']['type'] == 'playlist':
        source_id = uri_to_id(r['context']['uri'])

    if not target_playlist:
        p.remove_track(source_id, track)
        return "\"{}\" deleted from current playlist".format(track_name)

    playlists = p.get_playlists_short()
    target = [x for x in playlists if x['name'].lower() == target_playlist]
    if len(target) == 1:
        target = target[0]
    else:
        return "No such playlist '{}'".format(target_playlist)
    target_uri = target['uri']
    target_name = target['name']
    target_id = uri_to_id(target_uri)
    p.add_track(target_id, track)
    if add:
        return "\"{}\" added to \"{}\"".format(track_name, target_name)
    else:
        p.remove_track(source_id, track)
        return "\"{}\" moved to \"{}\"".format(track_name, target_name)

app = Flask(__name__)

def handle_api(action):
    j = request.get_json()
    # if there is no json lets try to manually decode the string
    if not j:
        try:
            j = json.loads(request.data.decode())
        except ValueError:
            j = None
    if not j:
        error = "Invalid api_key (no JSON body)"
        LOG.info(error)
        return error, 403
    if j.get('api_key', None) != "FcZzT3FQgNDLkZVt9WvhPXdcf5sszE1N":
        error = "Invalid api_key"
        LOG.info(error)
        return error, 403

    if action == "del":
        result = move_current_song(None)

    target_playlist = j['target_playlist']
    if not target_playlist:
        error = "No target_playlist"
        LOG.info(error)
        return error, 403

    if action == "move":
        result = move_current_song(target_playlist, add=False)
    if action == "add":
        result = move_current_song(target_playlist, add=True)
    LOG.info(result)
    return result, 200


# here is how we are handling routing with flask:
@app.route('/move', methods=['POST'])
def move():
    return handle_api("move")

@app.route('/add', methods=['POST'])
def add():
    return handle_api("add")

@app.route('/del', methods=['POST'])
def delete():
    return handle_api("del")

if __name__ == '__main__':
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter(
        '%(asctime)s - [%(name)s] - [%(levelname)s] - %(message)s'))
    logging.getLogger().addHandler(ch)

    move_current_song(None, None)


