Spotify Backup and API
======================

Deployment
----------

Useful commands:
```bash
source env/bin/activate     # activate python virtual environ
virtualenv env -p python3.6 # make a new virtual env with correct python version
zappa deploy dev            # deploy app for first time
zappa update dev            # update code (some aws structures not updated)
```
