#!/bin/sh
# Build the matching Qt 6 plugin in an isolated prefix.
set -eu
work=${1:?Usage: build-layer-shell.sh /path/to/private-build-directory}
mkdir -p "$work"
work=$(realpath "$work")
archive="$work/layer-shell-qt-5.27.11.tar.xz"
if [ ! -f "$archive" ]; then
    curl -fL --max-time 60 https://download.kde.org/stable/plasma/5.27.11/layer-shell-qt-5.27.11.tar.xz -o "$archive"
fi
printf '%s  %s\n' f4c321091619c9aeffe9e3568ff22ba4434538dcb3e89e6e23f5950d1e76d350 "$archive" | sha256sum -c -
mkdir -p "$work/source"
tar -xf "$archive" -C "$work/source" --strip-components=1
cmake -S "$work/source" -B "$work/build" -DQT_MAJOR_VERSION=6 -DBUILD_TESTING=OFF \
    -DBUILD_SHARED_LIBS=ON -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$work/install"
cmake --build "$work/build" -j2
cmake --install "$work/build"
