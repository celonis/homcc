.ONESHELL:

all: server client

server: 
	echo "Building the homcc server .deb"

	cp setup_server.py setup.py
	python3 setup.py --command-packages=stdeb.command sdist_dsc --with-dh-systemd

	echo "-- Copying service file"
	# we need to copy the systemd service file to the generated package
	cd deb_dist/homccd-*
	cp ../../debian/homccd.service debian/service

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
	python3 setup.py --command-packages=stdeb.command bdist_deb

	echo "-- Copying client .deb into target"
	mkdir -p target
	cp deb_dist/*.deb target/homcc.deb

	rm setup.py
	rm -rf deb_dist


homcc: client

homccd: server

clean:
	rm -rf target/*.deb
