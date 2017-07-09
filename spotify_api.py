#!/usr/bin/env python3
import requests
import cachecontrol
import copy
from secret import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
import boto
import os
import json


ACCESS_TOKEN_KEY = 'access-token.json'


TOKEN_URL = 'https://accounts.spotify.com/api/token'
RECENTLY_PLAYED_URL = 'https://api.spotify.com/v1/me/player/recently-played'


class Puller:
    def __init__(self):
        self.sess = cachecontrol.CacheControl(requests.Session())
        self.auth = (CLIENT_ID, CLIENT_SECRET)
        self.access_token = self._refresh_token()

    # def _get_key(self):
    #     connection = boto.s3.connect_to_region('us-east-1')
    #     stage = os.environ.get('STAGE', 'dev')
    #     bucket = connection.get_bucket('spotifyapi-' + stage)
    #     return bucket.get_key(ACCESS_TOKEN_KEY, validate=False)
        
    # def _set_key(self, data):
    #     self.key.set_contents_from_string(data)

    # def _get_key_val(self):
    #     return self.key.get_contents_as_string(encoding='utf-8')

    def _refresh_token(self):
        data = {
                'grant_type': 'refresh_token',
                'refresh_token': REFRESH_TOKEN
        }
        r = self.sess.post(TOKEN_URL, auth=self.auth, data=data)
        return r.json()['access_token']

    def get_recently_played(self):
        payload = {
                "token_type": "bearer"
        }
        r = self.sess.get(RECENTLY_PLAYED_URL, auth=self.auth, params=payload)
        print(r.text)


def main():
    p = Puller()
    print(p.access_token)


def lambda_handler(event, context):
    main()


if __name__ == '__main__':
    main()

