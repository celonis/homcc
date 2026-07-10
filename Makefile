.ONESHELL:
# abort a recipe as soon as any command fails instead of limping on to later steps;
# without this a failing `sdist_dsc` (e.g. missing/incompatible stdeb) is masked by a
# confusing "debian/changelog missing" error from dpkg-buildpackage running in the wrong directory
.SHELLFLAGS := -ec

# interpreter used to run the stdeb build; override for a Python that has a working stdeb,
# e.g. `make PYTHON=python3.11 all` (stdeb 0.10.0 does not run on Python 3.12+)
PYTHON ?= python3

all: server client

DEBIAN_SRC := ../../debian

server: 
	echo "Building the homcc server .deb"

	cp setup_server.py setup.py
	$(PYTHON) setup.py --command-packages=stdeb.command sdist_dsc --with-dh-systemd

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
	$(PYTHON) setup.py --command-packages=stdeb.command sdist_dsc

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
