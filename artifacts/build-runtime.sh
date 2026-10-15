#!/bin/bash
# Build the coredla-runtime artifact: ../build/coredla-runtime-<ver>.mender.
# Payload = runtime.tar: freshly built dla-server + wrapper + service + the
# library set proven on the board (pulled once from terasic@coredla:app/ into
# ../build/runtime-libs; three of them differ from the host build tree, the
# board's are the ones that work). Version = payload hash. build_version.txt is
# read by the FPGA plugin from COREDLA_ROOT and must match the graph.
set -eu
cd "$(dirname "$0")/.."
LIBS=build/runtime-libs
BOARD=${BOARD:-terasic@coredla}
if [ ! -d $LIBS ]; then
    mkdir -p $LIBS/hetero_plugin
    scp -q $BOARD:app/{plugins.xml,build_version.txt,build_os.txt,libcoreDlaRuntimePlugin.so,libhps_platform_mmd.so,libdla_compiled_result.so,libopenvino.so.2460,libopenvino_arm_cpu_plugin.so,libopenvino_ir_frontend.so.2460,libopencv_core.so.408,libopencv_imgcodecs.so.408,libopencv_imgproc.so.408} $LIBS/
    scp -q $BOARD:app/hetero_plugin/libcoreDLAHeteroPlugin.so $LIBS/hetero_plugin/
    scp -qr $BOARD:app/sdklibs $LIBS/
    ln -s libopenvino.so.2460 $LIBS/libopenvino.so
fi
if [ ! -f $LIBS/libjpeg.so.8 ]; then  # live.jpg encoder: the board OpenCV has no JPEG codec
    scp -q $BOARD:/usr/lib/aarch64-linux-gnu/libjpeg.so.8 $LIBS/
fi
dla-server/build.sh >/dev/null
STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
cp -r $LIBS/. "$STAGE/"
cp dla-server/build/dla-server board/dla-server.sh board/dla-server.service "$STAGE/"
# Deterministic tar so the version hash only moves when the payload does.
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf build/runtime.tar -C "$STAGE" .
VER=$(sha256sum build/runtime.tar | cut -c1-8)
NAME=coredla-runtime-$VER
mender-artifact write module-image -T coredla-runtime -t de25-nano -n "$NAME" -o build/$NAME.mender -f build/runtime.tar >/dev/null
ls -l build/$NAME.mender
