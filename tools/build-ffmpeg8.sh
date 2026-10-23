#!/usr/bin/env bash
# Private FFmpeg ABI for GE-Proton's winedmo. Builds under .tmp/ffmpeg8 and installs the libraries into
# ${FFMPEG8_DIR:-~/.local/share/san11/ffmpeg8}/{x86_64,i386}, where the launcher looks for them.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$repo"
export TMPDIR="$repo/.tmp"
export LC_ALL=C CCACHE_DISABLE=1
# Do not inherit an unbounded parallel make from the caller.
unset MAKEFLAGS MFLAGS

version=8.0.3
sha256=6136812ea6d4e68bdba27e33c2a94382711cdf4f8602ffef056ff792bd6f9818
signer=FCF986EA15E6E293A5644F10B4322F04D67658D8
base="$TMPDIR/ffmpeg8"
downloads="$base/downloads"
src="$base/src/ffmpeg-$version"
jobs=${JOBS:-6}
if [[ ! $jobs =~ ^[1-6]$ ]]; then
    printf '%s\n' 'JOBS must be between 1 and 6.' >&2
    exit 1
fi
for tool in gcc make curl gpg tar xz sha256sum objdump; do
    command -v "$tool" >/dev/null || { printf 'Missing tool: %s\n' "$tool" >&2; exit 1; }
done
mkdir -p "$downloads" "$base/src" "$base/logs" "$base/checks" "$base/gnupg"
chmod 700 "$base/gnupg"

fetch() {
    local url=$1 dest=$2
    if [[ ! -s $dest ]]; then
        curl --fail --location --proto '=https' --tlsv1.2 --retry 3 \
            "$url" -o "$dest.part"
        mv -- "$dest.part" "$dest"
    fi
}

fetch "https://ffmpeg.org/releases/ffmpeg-$version.tar.xz" "$downloads/ffmpeg-$version.tar.xz"
fetch "https://ffmpeg.org/releases/ffmpeg-$version.tar.xz.asc" "$downloads/ffmpeg-$version.tar.xz.asc"
fetch https://ffmpeg.org/ffmpeg-devel.asc "$downloads/ffmpeg-devel.asc"
printf '%s  %s\n' "$sha256" "$downloads/ffmpeg-$version.tar.xz" | sha256sum --check

# Isolated keyring: never import into ~/.gnupg or start its agents.
gpg_args=(--no-options --homedir "$base/gnupg" --batch --no-autostart)
gpg "${gpg_args[@]}" --import "$downloads/ffmpeg-devel.asc" > "$base/logs/key-import.log" 2>&1
gpg "${gpg_args[@]}" --status-fd=1 --verify \
    "$downloads/ffmpeg-$version.tar.xz.asc" "$downloads/ffmpeg-$version.tar.xz" \
    > "$base/logs/signature.log" 2>&1
if ! grep -Fq "[GNUPG:] VALIDSIG $signer " "$base/logs/signature.log"; then
    cat "$base/logs/signature.log" >&2
    exit 1
fi
printf 'Verified FFmpeg %s (SHA-256 and signature by %s).\n' "$version" "$signer"
if [[ ! -f $src/configure ]]; then
    tar -xJf "$downloads/ffmpeg-$version.tar.xz" -C "$base/src"
fi

common=(
    --enable-shared --disable-static --enable-pic --disable-debug --disable-doc
    --disable-autodetect --disable-network --disable-hwaccels --disable-v4l2-m2m
    --disable-programs --enable-ffprobe --disable-avdevice --disable-avfilter
    --disable-everything --enable-avutil --enable-avcodec --enable-avformat
    --enable-swscale --enable-swresample --disable-x86asm
    '--enable-demuxer=mpegps,mpegts,mpegvideo,avi,asf,mov,matroska,wav,mp3,ogg,bink'
    '--enable-decoder=mpeg1video,mpeg2video,mpeg4,msmpeg4v1,msmpeg4v2,msmpeg4v3,wmv1,wmv2,h264,mp1,mp2,mp3,pcm_*,adpcm_*,vorbis,wmav1,wmav2,aac,bink,binkaudio_dct,binkaudio_rdft'
    '--enable-parser=mpegvideo,mpegaudio,h264,aac' --enable-protocol=file
)
sonames=(libavutil.so.60 libavformat.so.62 libavcodec.so.62 libswscale.so.9 libswresample.so.6)

build_arch() {
    local arch=$1
    shift
    local prefix="$base/$arch" build="$base/build-$arch"
    mkdir -p "$build"
    (
        cd -- "$build"
        args=("--prefix=$prefix" "--libdir=$prefix/lib" "${common[@]}" "$@")
        printf '%q ' "$src/configure" "${args[@]}" > "$base/logs/$arch-configure-command.txt"
        printf '\n' >> "$base/logs/$arch-configure-command.txt"
        printf 'Configuring %s; logs: %s/logs/%s-*.log\n' "$arch" "$base" "$arch"
        if ! "$src/configure" "${args[@]}" > "$base/logs/$arch-configure.log" 2>&1; then
            tail -60 "$base/logs/$arch-configure.log" >&2
            exit 1
        fi
        if ! make -j"$jobs" > "$base/logs/$arch-make.log" 2>&1; then
            tail -60 "$base/logs/$arch-make.log" >&2
            exit 1
        fi
        make install > "$base/logs/$arch-install.log" 2>&1
    )
    # Fail if any non-system external library slips into the private build.
    : > "$base/checks/$arch-elf.txt"
    local name needed
    for name in "${sonames[@]}"; do
        objdump -p "$prefix/lib/$name" >> "$base/checks/$arch-elf.txt"
        if objdump -p "$prefix/lib/$name" | grep -q TEXTREL; then
            printf 'Unexpected text relocations: %s\n' "$prefix/lib/$name" >&2
            exit 1
        fi
        if ! objdump -p "$prefix/lib/$name" | awk '$1 == "SONAME" { print $2 }' | grep -Fxq "$name"; then
            printf 'Unexpected SONAME: %s\n' "$name" >&2
            exit 1
        fi
        while read -r needed; do
            case "$needed" in
                libc.so.6|libm.so.6|libpthread.so.0|libdl.so.2|librt.so.1|libgcc_s.so.1|ld-linux*.so.*) ;;
                libavutil.so.60|libavformat.so.62|libavcodec.so.62|libswscale.so.9|libswresample.so.6) ;;
                *) printf 'Unexpected dependency in %s: %s\n' "$name" "$needed" >&2; exit 1 ;;
            esac
        done < <(objdump -p "$prefix/lib/$name" | awk '$1 == "NEEDED" { print $2 }')
    done
    printf 'Installed and checked %s/lib\n' "$prefix"
}

build_arch x86_64 --arch=x86_64 --cc=gcc

# Test linking, not execution: sandboxes can reject 32-bit syscalls (SIGSYS).
cat > "$base/checks/m32.c" <<'EOF'
#include <stdio.h>
#include <pthread.h>
#include <math.h>
int main(void) { puts("m32-ok"); return 0; }
EOF
if gcc -m32 "$base/checks/m32.c" -o "$base/checks/m32" -lm -pthread \
    > "$base/logs/m32-toolchain.log" 2>&1; then
    # Cross mode avoids executing configure's target probes on this host.
    # Some upstream i386 inline assembly emits text relocations even with PIC.
    build_arch i386 --arch=x86_32 --cc='gcc -m32' --enable-cross-compile --target-os=linux --disable-inline-asm
    printf '%s\n' 'i386 built (gcc -m32 linked successfully; target execution is a separate check).' \
        | tee "$base/checks/i386-status.txt"
else
    printf '%s\n' 'i386 skipped: gcc -m32 could not link with lib32 glibc; see logs/m32-toolchain.log.' \
        | tee "$base/checks/i386-status.txt"
fi

out=${FFMPEG8_DIR:-$HOME/.local/share/san11/ffmpeg8}
for arch in x86_64 i386; do
    [[ -d $base/$arch/lib ]] || continue
    mkdir -p -- "$out/$arch"
    cp -a -- "$base/$arch"/lib/lib*.so* "$out/$arch/"
    printf '%s libraries: %s/%s\n' "$arch" "$out" "$arch"
done
