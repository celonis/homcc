#!/bin/bash

FILE="/etc/schroot/chroot.d/$1.conf"

cat > $FILE << EOF
[$1]
description=Test Environment $1
directory=/var/chroot/$1
root-users=$2
users=$2
type=directory
EOF