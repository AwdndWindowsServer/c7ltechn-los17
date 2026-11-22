#!/bin/bash
# =============================================================================
#  20-unpack.sh — 下载并解开 donor（mido LineageOS 17.1）与 C7 素材
# =============================================================================
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/config.sh"

D="$WORK/donor"; mkdir -p "$D"

# ---------------------------------------------------------------- 1. donor zip
fetch "$DONOR_URL" "$D/$DONOR_NAME"
[ -s "$D/$DONOR_NAME" ] || die "donor 包下载失败"
log "[1/5] donor 包: $(basename "$DONOR_NAME") ($(du -h "$D/$DONOR_NAME" | cut -f1))"

rm -rf "$D/extracted"; mkdir -p "$D/extracted"
log "[2/5] 解出关键文件 …"
unzip -o -q "$D/$DONOR_NAME" -d "$D/extracted" \
  'system*' 'vendor*' 'boot.img' 'META-INF/com/google/android/update-binary' \
  'META-INF/com/android/metadata' 'file_contexts*' 2>/dev/null || true
( cd "$D/extracted" && ls -la | sed 's/^/      /' )

SYS_SRC=""
for c in system.img system.new.dat.br system.new.dat system.new.dat.gz system.new.dat.xz; do
  [ -e "$D/extracted/$c" ] && { SYS_SRC="$c"; break; }
done
[ -n "$SYS_SRC" ] || die "donor 包里找不到 system 镜像（$D/extracted）"

VEN_SRC=""
for c in vendor.img vendor.new.dat.br vendor.new.dat; do
  [ -e "$D/extracted/$c" ] && { VEN_SRC="$c"; break; }
done
[ -e "$D/extracted/boot.img" ] || die "donor 包里没有 boot.img"

# ---------------------------------------------------------------- 2. dat → img
if [ ! -s "$D/system.img" ]; then
  if [ "$SYS_SRC" = "system.img" ]; then
    log "[3/5] donor 直接给的是 system.img，复制 …"
    cp --sparse=always "$D/extracted/system.img" "$D/system.img"
  else
    log "[3/5] $SYS_SRC → system.img (解压 + 稀疏重建) …"
    python3 "$TOOLS/sdat2img.py" "$D/extracted/system.transfer.list" \
            "$D/extracted/$SYS_SRC" "$D/system.img"
  fi
fi
log "    system.img: $(du -h "$D/system.img" | cut -f1) (表观 $(du -h --apparent-size "$D/system.img" | cut -f1))"

if [ -n "$VEN_SRC" ] && [ ! -s "$D/vendor.img" ]; then
  if [ "$VEN_SRC" = "vendor.img" ]; then
    cp --sparse=always "$D/extracted/vendor.img" "$D/vendor.img"
  else
    log "[3/5] $VEN_SRC → vendor.img …"
    python3 "$TOOLS/sdat2img.py" "$D/extracted/vendor.transfer.list" \
            "$D/extracted/$VEN_SRC" "$D/vendor.img"
  fi
fi
[ -s "$D/vendor.img" ] && log "    vendor.img: $(du -h "$D/vendor.img" | cut -f1)" || log "    （donor 没有独立 vendor 镜像：vendor-in-system 布局）"

# ---------------------------------------------------------------- 3. boot 拆包
if [ ! -s "$D/donor-boot/ramdisk.cpio" ]; then
  log "[4/5] 拆 donor boot.img（取 Android 10 的 init ramdisk）…"
  python3 "$TOOLS/bootimg.py" unpack "$D/extracted/boot.img" "$D/donor-boot" | sed 's/^/      /'
fi
[ -s "$D/donor-boot/ramdisk.cpio" ] || die "donor ramdisk 解压失败"

# ---------------------------------------------------------------- 4. C7 blobs（可选）
if [ "$C7_BLOBS" = "1" ]; then
  if [ ! -d "$C7_VENDOR_DIR" ] && [ -n "$C7_VENDOR_TARBALL" ]; then
    log "[5/5] 取 C7 原厂 vendor/system blob 树 …"
    fetch "$C7_VENDOR_TARBALL" "$WORK/c7vendor.tar.gz"
    mkdir -p "$WORK/vendor-src"
    tar xzf "$WORK/c7vendor.tar.gz" -C "$WORK/vendor-src" --strip-components=1
  fi
  if [ -d "$C7_VENDOR_DIR" ]; then
    log "    C7 vendor blob: $(find "$C7_VENDOR_DIR/vendor" -type f 2>/dev/null | wc -l) 个文件"
  else
    warn "C7_BLOBS=1 但找不到 blob 树: $C7_VENDOR_DIR（将跳过叠加）"
    C7_BLOBS=0
  fi
else
  log "[5/5] 跳过 C7 blob 叠加（C7_BLOBS=0，第一版只验证内核/显示链路）"
fi

# ---------------------------------------------------------------- 5. 摘要
python3 - "$D" <<'PY'
import json, os, sys
d = sys.argv[1]
out = {
    "donor_zip": os.path.basename([f for f in os.listdir(d) if f.endswith(".zip")][0]),
    "system_img": os.path.getsize(f"{d}/system.img"),
    "vendor_img": os.path.getsize(f"{d}/vendor.img") if os.path.exists(f"{d}/vendor.img") else 0,
    "boot_img": os.path.getsize(f"{d}/extracted/boot.img"),
}
json.dump(out, open(f"{d}/donor.json", "w"), indent=2)
print("    donor 摘要:", json.dumps(out, ensure_ascii=False))
PY
log "解开完成。下一步: 30-assemble-system.sh"
