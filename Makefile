.ONESHELL:

all: server client

DEBIAN_SRC := ../../debian

server: 
	echo "Building the homcc server .deb"

	cp setup_server.py setup.py
	python3 setup.py --command-packages=stdeb.command sdist_dsc --with-dh-systemd

	echo "-- Copying service file"
	# we need to copy the systemd service file to the generated package
	cd deb_dist/homccd-*
	cp $(DEBIAN_SRC)/homccd.service debian/service
	cp $(DEBIAN_SRC)/compat debian/compat

	echo "-- Building server .deb package"
	dpkg-buildpackage -rfakeroot -uc -us
	cd ../..

	echo "-- Copying server .deb into target"
	mkdir -p target
	cp deb_dist/*.deb target/homccd.deb

	rm setup.py
	rm -rf deb_dist

client:
	echo "Building the homcc client .deb"

	cp setup_client.py setup.py
	python3 setup.py --command-packages=stdeb.command sdist_dsc --with-dh-systemd

	cd deb_dist/homcc-*
	cp $(DEBIAN_SRC)/compat debian/compat

	echo "-- Building client .deb package"
	dpkg-buildpackage -rfakeroot -uc -us
	cd ../..

	echo "-- Copying client .deb into target"
	mkdir -p target
	cp deb_dist/*.deb target/homcc.deb

	rm setup.py
	rm -rf deb_dist


homcc: client

homccd: server

clean:
	rm -rf target/*.deb
	rm -f homcc*.tar.gz
