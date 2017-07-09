#!/usr/bin/env python3
import requests
import cachecontrol


class Puller:
    def __init__(self):
        this.sess = cachecontrol.CacheControl(requests.Session())
        


def main():
    pass


def lambda_handler(event, context):
    main()


if __name__ == '__main__':
    main()

