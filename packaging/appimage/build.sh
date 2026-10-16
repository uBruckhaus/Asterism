#!/bin/sh
# Build Asterism-<version>-x86_64.AppImage: the app's Python files, desktop entry and icon; Python,
# PyGObject, GTK 4 and libadwaita come from the system (AppRun checks them).
# Needs appimagetool (https://github.com/AppImage/appimagetool/releases): check its SHA-256 before use.
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
version=${1:?usage: build.sh <version> [appimagetool]}
tool=${2:-appimagetool}
dir=$(mktemp -d)/Asterism.AppDir
mkdir -p "$dir/usr/lib/asterism"
cp "$root"/*.py "$dir/usr/lib/asterism/"
cp "$root/packaging/appimage/AppRun" "$dir/AppRun"
cp "$root/data/io.github.ubruckhaus.Asterism.desktop" "$dir/"
cp "$root/data/icons/io.github.ubruckhaus.Asterism.svg" "$dir/"
mkdir -p "$dir/usr/share/metainfo"
cp "$root/data/io.github.ubruckhaus.Asterism.metainfo.xml" "$dir/usr/share/metainfo/"
ARCH=x86_64 "$tool" "$dir" "$root/Asterism-$version-x86_64.AppImage"
sha256sum "$root/Asterism-$version-x86_64.AppImage"
