#!/bin/bash
# =============================================================================
#  50-make-zip.sh — 打包 TWRP 卡刷包（并可选生成 Odin 线刷 tar）
#
#  产物：
#    out/lineage-17.1-<date>-UNOFFICIAL-c7ltechn-port-kernel<ver>.zip   TWRP 卡刷
#    out/c7ltechn-port-odin-<date>.tar.md5                              Odin/搞机助手 AP 线刷
# =============================================================================
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/config.sh"

BUILD="$WORK/build"
SYS_IMG="$BUILD/system.img"
BOOT_IMG="$BUILD/boot.img"
[ -s "$SYS_IMG" ] || die "缺少 $SYS_IMG（先跑 30-assemble-system.sh）"
[ -s "$BOOT_IMG" ] || die "缺少 $BOOT_IMG（先跑 40-make-bootimg.sh）"

DATE=$(date +%Y%m%d)
KVER=$(cat "$BUILD/KERNEL_VERSION" 2>/dev/null || echo unknown)
KSLUG=$(echo "$KVER" | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1 || true)
[ -z "$KSLUG" ] && KSLUG=unknown
ZIPNAME="${PORT_TAG}-${DATE}-UNOFFICIAL-kernel${KSLUG}.zip"

ZIPDIR="$BUILD/zip"; rm -rf "$ZIPDIR"; mkdir -p "$ZIPDIR/META-INF/com/google/android"

log "[1/4] 复制镜像到打包目录 …"
cp --sparse=always "$SYS_IMG" "$ZIPDIR/system.img"
cp -f "$BOOT_IMG" "$ZIPDIR/boot.img"
if [ -d "$BUILD/vendor-modules" ]; then cp -a "$BUILD/vendor-modules" "$ZIPDIR/modules"; fi

log "[2/4] 生成 updater-script …"
cat > "$ZIPDIR/META-INF/com/google/android/updater-script" <<EOF
ui_print("==================================================");
ui_print(" LineageOS ${LOS_VERSION} (Android ${ANDROID_VER}) for");
ui_print(" Samsung Galaxy C7  SM-C7000 / c7ltechn");
ui_print(" 纯移植版  donor: ${DONOR_DEVICE} LineageOS ${LOS_VERSION}");
ui_print(" 内核: ${KVER}");
ui_print("==================================================");
ui_print("");
ui_print("目标分区: system=${PART_SYSTEM_SIZE}B  boot=${PART_BOOT_SIZE}B");
show_progress(0.02, 20);

ui_print(">> 写入 boot 分区 (C7 4.9 内核 + Android 10 init ramdisk)");
package_extract_file("boot.img", "$BYNAME/boot");
show_progress(0.10, 20);

ui_print(">> 写入 system 分区（约 3.5 GB，eMMC 上需 3~8 分钟）");
package_extract_file("system.img", "$BYNAME/system");
show_progress(0.85, 60);

ifelse(file_getprop("/system/build.prop", "ro.build.version.release") != "", 
    ui_print(">> 检测到已有系统，清理不匹配的 vendor/modules"), ui_print(">> 全新安装"));
ifelse(is_mounted("/system"), unmount("/system"));
ifelse(is_mounted("/vendor"), unmount("/vendor"));
ifelse(is_mounted("/data"),  unmount("/data"));

ui_print(">> 完成。");
ui_print("");
ui_print("重要：首次刷入必须【格式化 data】（TWRP: 清除 → 格式化 Data 分区）。");
ui_print("      另请提前备份 EFS / modemst1 / modemst2 / persist。");
ui_print("首启 3~10 分钟属正常；黑屏卡住请连电脑抓 logcat / dmesg。");
EOF

log "[3/4] 写入 update-binary（取自 donor OTA 包，arm64）…"
UPDATE_BIN="$WORK/donor/extracted/META-INF/com/google/android/update-binary"
if [ ! -s "$UPDATE_BIN" ]; then
  mkdir -p "$(dirname "$UPDATE_BIN")"
  unzip -o -q "$WORK/donor/$DONOR_NAME" "META-INF/com/google/android/update-binary" -d "$WORK/donor/extracted"
fi
[ -s "$UPDATE_BIN" ] || die "donor 包里没有 update-binary"
cp -f "$UPDATE_BIN" "$ZIPDIR/META-INF/com/google/android/update-binary"
chmod 0755 "$ZIPDIR/META-INF/com/google/android/update-binary"

log "[4/4] 压缩 zip …"
( cd "$ZIPDIR" && zip -r -q -9 "$OUT/$ZIPNAME" . -x '.*' )
log "产物: $OUT/$ZIPNAME ($(du -h "$OUT/$ZIPNAME" | cut -f1))"

# 单刷 boot.img 的场景（heimdall / fastboot）单独放一份
cp -f "$BOOT_IMG" "$OUT/boot.img"
if [ -d "$BUILD/vendor-modules" ]; then ( cd "$BUILD" && tar czf "$OUT/vendor-modules.tar.gz" vendor-modules ); fi
log "已附带: out/boot.img ($(stat -c%s "$OUT/boot.img") B)"

if [ "${MAKE_ODIN:-0}" = "1" ]; then
  log "生成 Odin AP tar.md5 …"
  ODIR="$BUILD/odin"; rm -rf "$ODIR"; mkdir -p "$ODIR"
  cp --sparse=always "$SYS_IMG" "$ODIR/system.img"
  cp -f "$BOOT_IMG" "$ODIR/boot.img"
  TARB="$OUT/c7ltechn-port-odin-$DATE.tar"
  ( cd "$ODIR" && tar -H ustar -cf "$TARB" boot.img system.img )
  MD5=$(md5sum "$TARB" | cut -d' ' -f1)
  printf '%s' "$MD5" > "$OUT/c7ltechn-port-odin-$DATE.tar.md5"
  cat "$TARB" >> "$OUT/c7ltechn-port-odin-$DATE.tar.md5"
  rm -f "$TARB"; rm -rf "$ODIR"
  log "产物: $OUT/c7ltechn-port-odin-$DATE.tar.md5 ($(du -h "$OUT/c7ltechn-port-odin-$DATE.tar.md5" | cut -f1))"
fi
