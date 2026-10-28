#!/bin/sh
# Runs after the templates are rendered. nginx cannot start when it listens on [::]
# and the host has IPv6 turned off, so drop that listen there.
set -eu
conf=/etc/nginx/conf.d/default.conf
if [ ! -f /proc/net/if_inet6 ] && [ -f "$conf" ]; then
  sed -i '/listen \[::\]/d' "$conf"
  echo "$0: IPv6 is not available; listening on IPv4 only"
fi
