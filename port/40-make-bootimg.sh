#!/bin/bash
# =============================================================================
#  40-make-bootimg.sh — 组装 C7 的 boot.img（LineageOS 17.1）
#
#  = donor(mido Android 10) 的 init ramdisk（只做最小修补：去掉 fstab 的 verify）
#  + C7 的 Linux 4.9.337 内核（Image.gz-dtb）
#  + 用 kernel 编出的 msm8953-c7ltechn.dtb 生成 QCDT 表（三星 aboot 按 msm-id/board-id 选表项）
#  = 三星 v0 头 + dt 区 + SEANDROIDENFORCE，按 C7 PIT 的 BOOT(32 MiB) 打包
# =============================================================================
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/config.sh"

DONOR_BOOT="$WORK/donor/donor-boot"
[ -d "$DONOR_BOOT" ] || die "缺少 donor boot 拆包目录，先跑 20-unpack.sh"
[ -s "$C7_KERNEL_DIR/kernel" ] || die "缺少 C7 内核: $C7_KERNEL_DIR/kernel（先跑 .github/workflows/kernel.yml 或手工放入）"

BUILD="$WORK/build"; BOOTDIR="$BUILD/boot"; mkdir -p "$BOOTDIR"

# ---------------------------------------------------------------- 1. ramdisk
log "[1/5] 解 donor ramdisk 并做最小修补 …"
rm -rf "$BOOTDIR/ramdisk.dir"; mkdir -p "$BOOTDIR/ramdisk.dir"
( cd "$BOOTDIR/ramdisk.dir" && cpio -idm --quiet < "$DONOR_BOOT/ramdisk.cpio" )
log "    ramdisk 条目: $(find "$BOOTDIR/ramdisk.dir" | wc -l)"

# fstab：去掉 verify（系统是重新组装的，没有 AVB 签名），并确认 system/data 项存在
FSTABS=$(find "$BOOTDIR/ramdisk.dir" -name 'fstab*' -type f 2>/dev/null || true)
[ -n "$FSTABS" ] || warn "ramdisk 里没找到 fstab*，保持原样（Android 10 的 first-stage 可能用 system/etc/fstab.qcom）"
for f in $FSTABS; do
  cp -a "$f" "$f.orig"
  sed -i -E 's/,verify(=[a-z]+)?//g; s/,avb(=[a-z]+)?//g' "$f"
  log "    修补 $(realpath --relative-to="$BOOTDIR/ramdisk.dir" "$f")"
  grep -nE 'system|userdata|vendor' "$f" | head -8 | sed 's/^/      /' || true
done

log "[2/5] 重新打包 ramdisk（newc cpio + gzip）…"
python3 "$TOOLS/bootimg.py" rd-pack "$BOOTDIR/ramdisk.dir" "$BOOTDIR/ramdisk.cpio"
gzip -9 -n -c "$BOOTDIR/ramdisk.cpio" > "$BOOTDIR/ramdisk.cpio.gz"

# ---------------------------------------------------------------- 2. 内核 + DTB
log "[3/5] 准备内核与 QCDT dt 区 …"
cp -f "$C7_KERNEL_DIR/kernel" "$BOOTDIR/kernel"
DTB_SRC=""
for c in "$C7_KERNEL_DIR/dtb" "$C7_KERNEL_DIR/msm8953-c7ltechn.dtb" "$C7_KERNEL_DIR/dtbs/msm8953-c7ltechn.dtb"; do
  [ -s "$c" ] && { DTB_SRC="$c"; break; }
done
[ -n "$DTB_SRC" ] || die "缺少 C7 的 dtb（msm8953-c7ltechn.dtb）——没有它三星 aboot 选不到正确 DTB，必然黑屏重启"
python3 "$TOOLS/mkqcdt.py" "$BOOTDIR/dt.img" "$DTB_SRC" "$QCDT_MSM_ID" "$QCDT_BOARD_ID" "$QCDT_SUBTYPES"

# ---------------------------------------------------------------- 3. cmdline
DONOR_CMDLINE=$(python3 -c "import json,sys;print(json.load(open('$DONOR_BOOT/header.json')).get('cmdline',''))")
CMDLINE="$DONOR_CMDLINE"
# 首刷调试：permissive 方便看 avc 日志；C7 上 msm8953 通用参数沿用 donor
grep -q 'androidboot.selinux' <<<"$CMDLINE" || CMDLINE="$CMDLINE androidboot.selinux=permissive"
grep -q 'androidboot.hardware' <<<"$CMDLINE" || CMDLINE="$CMDLINE androidboot.hardware=qcom"
grep -q 'androidboot.console' <<<"$CMDLINE" || CMDLINE="$CMDLINE androidboot.console=ttyMSM0"
grep -q 'msm_rtb.filter' <<<"$CMDLINE" || CMDLINE="$CMDLINE msm_rtb.filter=0x237 ehci-hcd.park=3"
CMDLINE=$(echo "$CMDLINE" | sed -E 's/ +/ /g; s/^ //; s/ $//')
log "    cmdline: $CMDLINE"

# ---------------------------------------------------------------- 4. 打包
log "[4/5] 打包 boot.img（三星 v0 头 + dt 区 + SEANDROIDENFORCE）…"
python3 "$TOOLS/mkboot.py" \
  --kernel "$BOOTDIR/kernel" --ramdisk "$BOOTDIR/ramdisk.cpio.gz" --dt "$BOOTDIR/dt.img" \
  --cmdline "$CMDLINE" --out "$BUILD/boot.img" \
  --page 2048 --base 0x80000000 --kernel-offset 0x8000 --ramdisk-offset 0x01000000 \
  --tags-offset 0x100 --os-version "$ANDROID_VER" --os-patch 2020

# ---------------------------------------------------------------- 5. 校验/模块
BOOT_SIZE=$(stat -c%s "$BUILD/boot.img")
log "[5/5] boot.img = ${BOOT_SIZE} B，C7 BOOT 分区 = ${PART_BOOT_SIZE} B"
[ "$BOOT_SIZE" -le "$PART_BOOT_SIZE" ] || die "boot.img 超过 BOOT 分区（${BOOT_SIZE} > ${PART_BOOT_SIZE}）"

if [ -d "$C7_KERNEL_DIR/modules" ] && [ -n "$(ls -A "$C7_KERNEL_DIR/modules" 2>/dev/null)" ]; then
  log "内核模块: $(find "$C7_KERNEL_DIR/modules" -name '*.ko' | wc -l) 个 → 打包时覆盖到 /system/vendor/lib/modules"
  rm -rf "$BUILD/vendor-modules"; mkdir -p "$BUILD/vendor-modules"
  cp -a "$C7_KERNEL_DIR/modules/." "$BUILD/vendor-modules/"
else
  log "未提供内核模块（驱动若全部内建可忽略）"
fi

echo "C7 4.9.337 (kernel $(stat -c%s "$BOOTDIR/kernel") B)" > "$BUILD/KERNEL_VERSION"
log "boot.img 就绪。下一步: 50-make-zip.sh"
