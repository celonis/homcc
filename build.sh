#!/bin/bash

# TODO: list dependencies for building

echo "Building the homcc server .deb"

cp setup_server.py setup.py
python3 setup.py --command-packages=stdeb.command bdist_deb

SERVER_DEB_PATH=$(find deb_dist/ -name '*.deb')
cp $SERVER_DEB_PATH homcc_server.deb

rm setup.py
rm -rf deb_dist

echo "Building the homcc client .deb"

cp setup_client.py setup.py
python3 setup.py --command-packages=stdeb.command bdist_deb

CLIENT_DEB_PATH=$(find deb_dist/ -name '*.deb')
cp $CLIENT_DEB_PATH homcc_client.deb

rm setup.py
rm -rf deb_dist