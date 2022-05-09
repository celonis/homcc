#!/bin/sh

FILE="/etc/schroot/chroot.d/$1.conf"

cat > $FILE << EOF
[$1]
description=Test Environment $1
directory=/var/chroot/$1
root-groups=$2
type=directory
EOF
