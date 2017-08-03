#!/bin/bash

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root"
   exit 1
fi

set -e

wget http://www.haproxy.org/download/1.7/src/haproxy-1.7.8.tar.gz \
  -O ~/haproxy.tar.gz

tar xzvf ~/haproxy.tar.gz -C ~/

make -C ~/haproxy-1.7.8 TARGET=linux2628

make -C ~/haproxy-1.7.8 install

cp /usr/local/sbin/haproxy /usr/sbin/

mkdir -p /etc/haproxy
mkdir -p /run/haproxy
mkdir -p /var/lib/haproxy
touch /var/lib/haproxy/stats
chmod 777 /run/haproxy

useradd -r haproxy
