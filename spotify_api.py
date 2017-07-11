#!/usr/bin/env python3
import requests
import cachecontrol
import copy
from secret import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
import boto3
import os
import json
import datetime
import gzip


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
    'saved_tracks': 'https://api.spotify.com/v1/me/tracks'
}


class Puller:
    def __init__(self, verbose=True):
        self.verbose=verbose
        self.sess = cachecontrol.CacheControl(requests.Session())
        self.auth = (CLIENT_ID, CLIENT_SECRET)
        self.access_token = self._refresh_token()
        self.auth_headers = {"Authorization": "Bearer " + self.access_token}

    def _log(self, msg):
        if self.verbose:
            print(msg)

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
        elif code != 200:
            raise RuntimeError('returned status code {}'.format(code))
        else:
            return False

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

    def get_playlists(self):
        """gets user's list of playlists and their tracks

        Replaces the list of simple playlist with a list of full playlists, and
        replaces each full playlist's tracks field with a full list of tracks
        by unwrapping it from the paging object after fetching all pages. This
        returned object is not wrapped in a paging object.

        :returns: List of playlists (dict)
        :rtype: list

        """
        payload = {'limit': 50}
        self._log('fetching list of playlists')
        r = self.sess.get(URLS['list_playlists'],
                          params=payload, headers=self.auth_headers)
        if self._rate_limit_check(r):
            return self.get_playlists(self)
        j = r.json()
        playlists = self._iterate_paging_object(j)

        def get_full_playlist(playlist): 
            return self._get_a_playlist(playlist['owner']['id'],playlist['id'])

        return [get_full_playlist(p) for p in playlists]

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


def put_file(content):
    print('uploading')
    utc_datetime = datetime.datetime.utcnow()
    key_name = utc_datetime.strftime("%Y-%m-%d_%H%M%S_UTC.json.gz")

    stage = os.environ.get('STAGE', 'dev')
    bucket_name = 'spotifyapi-' + stage

    print('uploading to {} : {}'.format(bucket_name, key_name))
    s3 = boto3.resource('s3')
    object = s3.Object(bucket_name, key_name)
    object.put(Body=content)


def main():
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


def lambda_handler(event, context):
    main()


if __name__ == '__main__':
    main()

