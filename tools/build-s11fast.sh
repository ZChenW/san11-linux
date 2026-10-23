#!/usr/bin/env bash
# Build s11fast.dll and s11inject.exe (32-bit Windows, zig through uv) into ~/.local/share/san11/s11fast,
# where `san11 run` picks them up. See tools/s11fast/s11fast.c for what they do.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
out=${S11FAST_DIR:-$HOME/.local/share/san11/s11fast}
export TMPDIR="$repo/.tmp"
mkdir -p -- "$TMPDIR" "$out"
command -v uv >/dev/null || { printf '%s\n' 'Missing tool: uv (zig is fetched through it)' >&2; exit 1; }

cc() { uv tool run --from ziglang python -m ziglang cc -target x86-windows-gnu -O2 -Wall -Werror "$@"; }
cc -shared -o "$TMPDIR/s11fast.dll" "$repo/tools/s11fast/s11fast.c"
cc -Wl,--subsystem,windows -o "$TMPDIR/s11inject.exe" "$repo/tools/s11fast/s11inject.c" -lshell32
install -m 0644 "$TMPDIR/s11fast.dll" "$out/s11fast.dll"
install -m 0755 "$TMPDIR/s11inject.exe" "$out/s11inject.exe"
printf 'Built %s/{s11fast.dll,s11inject.exe}\n' "$out"
