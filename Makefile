.ONESHELL:

# Build all Debian binary packages (homcc, homccd, python3-homcc-common) from
# the hand-written debian/ directory and collect the resulting .deb files in
# ./target. dpkg-buildpackage writes its artifacts to the parent directory, so
# we copy them into ./target afterwards.

all: deb

deb:
	dpkg-buildpackage -rfakeroot -uc -us -b
	mkdir -p target
	cp ../homcc_*.deb ../homccd_*.deb ../python3-homcc-common_*.deb target/

# Convenience aliases. As all packages are produced by a single source
# package, these build everything.
homcc client: deb

homccd server: deb

clean:
	dpkg-buildpackage -rfakeroot -T clean || true
	rm -rf target
