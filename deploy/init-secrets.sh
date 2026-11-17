#!/bin/sh
# Generate random secret files for the optional postgres / minio profiles. Never overwrites existing files.
set -eu
dir="$(dirname "$0")/secrets"
mkdir -p "$dir"
gen() { [ -s "$dir/$1" ] || { umask 077; head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$dir/$1"; echo "created $dir/$1"; }; }
gen postgres_password
[ -s "$dir/minio_user" ] || { umask 077; printf 'acretia' > "$dir/minio_user"; echo "created $dir/minio_user"; }
gen minio_password
