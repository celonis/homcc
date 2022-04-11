.ONESHELL:

all: server client

server: 
	echo "Building the homcc server .deb"

	cp setup_server.py setup.py
	python3 setup.py --command-packages=stdeb.command sdist_dsc --with-dh-systemd --package homcc-server

	echo "-- Copying service file"
	# we need to copy the systemd service file to the generated package
	cd deb_dist/homcc-server-*
	cp ../../debian/homcc-server.service debian/service

	echo "-- Building server .deb package"
	dpkg-buildpackage -rfakeroot -uc -us
	cd ../..

	echo "-- Copying server .deb into target"
	mkdir -p target
	cp deb_dist/*.deb target/homcc_server.deb

	rm setup.py
	rm -rf deb_dist

client:
	echo "Building the homcc client .deb"

	cp setup_client.py setup.py
	python3 setup.py --command-packages=stdeb.command bdist_deb

	echo "-- Copying client .deb into target"
	cp deb_dist/*.deb target/homcc_client.deb

	rm setup.py
	rm -rf deb_dist