#!/bin/sh

FILE="/etc/schroot/chroot.d/$1.conf"
GROUPS=`id -nG | sed 's/ /,/g'`

cat > $FILE << EOF
[$1]
description=Test Environment $1
directory=/var/chroot/$1
root-groups=$GROUPS
groups=$GROUPS
type=directory
EOF
