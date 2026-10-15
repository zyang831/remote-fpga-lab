#!/bin/sh
# Launch dla-server from /opt/dla. Same ld.so trick as dla_benchmark.sh:
# the rootfs glibc (2.35) predates the Yocto SDK's, so load through the SDK's
# own dynamic linker. COREDLA_ROOT is demanded by the FPGA plugin at init.
cd "$(dirname "$0")"
export COREDLA_ROOT="$PWD"
exec ./sdklibs/ld-linux-aarch64.so.1 --library-path ./sdklibs:. ./dla-server "$@" ./plugins.xml
