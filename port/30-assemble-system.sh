#!/bin/bash
# =============================================================================
#  30-assemble-system.sh — 组装 C7 的 system.img
#
#  默认只做"最小改动"：donor 的 system 原样扩到 C7 SYSTEM 分区大小。
#  第一版的目的就是先验证「4.9 内核 + C7 面板驱动 + Android 10 用户态」能不能点亮，
#  用户态越接近 donor 原始状态，变量越少。
#
#  可选步骤（开关都在 config.sh / 环境变量）：
#    · donor 带独立 vendor.img → 合并进 /system/vendor，/vendor 做成符号链接
#    · C7_BLOBS=1 → 叠加 C7 原厂 blob（RIL/相机/传感器/音频参数/校准固件）
#    · PATCH_PROPS=1 → 改 build.prop 设备身份为 SM-C7000
# =============================================================================
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/config.sh"

DONOR_SYS="$WORK/donor/system.img"
DONOR_VND="$WORK/donor/vendor.img"
[ -s "$DONOR_SYS" ] || die "缺少 donor system.img，先跑 20-unpack.sh"

BUILD="$WORK/build"; SYS_IMG="$BUILD/system.img"; MNT="$BUILD/mnt"
mkdir -p "$BUILD" "$MNT"

if [ ! -s "$SYS_IMG" ]; then
  log "[1/6] 复制 donor system.img …"
  cp --sparse=always "$DONOR_SYS" "$SYS_IMG"
else
  log "[1/6] 复用已有 $SYS_IMG"
fi

DONOR_APPARENT=$(du -m --apparent-size "$SYS_IMG" | cut -f1)
TARGET_MB=$((SYSTEM_IMG_SIZE / 1024 / 1024))
log "    donor system: ${DONOR_APPARENT} MiB，C7 SYSTEM 可用: ${TARGET_MB} MiB"
[ "$DONOR_APPARENT" -le "$TARGET_MB" ] || die "donor system 比 C7 SYSTEM 分区还大（${DONOR_APPARENT} > ${TARGET_MB} MiB）"

log "[2/6] 扩容 ext4 到 ${TARGET_MB} MiB …"
truncate -s "$SYSTEM_IMG_SIZE" "$SYS_IMG"
e2fsck -f -y "$SYS_IMG" >/dev/null 2>&1 || true
resize2fs "$SYS_IMG" >/dev/null 2>&1 || warn "resize2fs 失败（空间够用即可继续）"

mountpoint -q "$MNT" && umount "$MNT"
mount -o loop,rw "$SYS_IMG" "$MNT"
trap 'umount "$MNT" 2>/dev/null || true' EXIT
FREE_MB=$(( $(df -k --output=avail "$MNT" | tail -1) / 1024 ))
log "    挂载 ok，可用空间 ${FREE_MB} MiB"
log "    根目录: $(ls "$MNT" | tr '\n' ' ')"

# ------------------------------------------------ 3. donor 独立 vendor 合并
if [ -s "$DONOR_VND" ]; then
  log "[3/6] donor 有独立 vendor.img → 合并进 /system/vendor …"
  rm -rf "$MNT/system/vendor"; mkdir -p "$MNT/system/vendor"
  VND_MNT="$BUILD/mnt-vnd"; mkdir -p "$VND_MNT"
  mountpoint -q "$VND_MNT" && umount "$VND_MNT"
  mount -o loop,ro "$DONOR_VND" "$VND_MNT"
  cp -a "$VND_MNT/." "$MNT/system/vendor/"
  umount "$VND_MNT"
  [ -L "$MNT/vendor" ] || { rm -rf "$MNT/vendor"; ln -s /system/vendor "$MNT/vendor"; }
  log "    vendor 文件数: $(find "$MNT/system/vendor" -type f | wc -l)，/vendor -> /system/vendor 已建立"
else
  log "[3/6] donor 是 vendor-in-system 布局，跳过 vendor 合并"
  if [ -e "$MNT/system/vendor" ]; then log "    /system/vendor 已存在（$(find "$MNT/system/vendor" -maxdepth 1 | wc -l) 项）"; fi
fi

# ------------------------------------------------ 3.5 fstab 清理（必须在 vendor 合并之后）
# C7 只有 boot/system/cache/persist/modem/apnhlos/dsp/efs/userdata 这些分区，
# donor 是另一台机器，fstab 里会挂着 C7 不存在的 by-name（cust/product/odm/vendor）。
# 这些行留着，first-stage init 会等一个永远不来的块设备 → 卡在开机动画/黑屏。
log "[3.5/6] 清理 fstab 里 C7 不存在的分区挂载 …"
C7_PARTITIONS=" boot system cache userdata persist modem apnhlos dsp efs modemst1 modemst2 fsg ssd "
for f in "$MNT/system/vendor/etc/fstab.qcom" "$MNT/system/etc/fstab.qcom" "$MNT/vendor/etc/fstab.qcom"; do
  [ -f "$f" ] || continue
  BEFORE=$(wc -l < "$f")
  cp -a "$f" "$f.orig"
  awk -v parts="$C7_PARTITIONS" '
    BEGIN { n=split(parts, P, " "); for (i=1;i<=n;i++) known[P[i]]=1 }
    /^[[:space:]]*#/ { print; next }
    NF < 2 { print; next }
    {
      src=$1; mnt=$2; keep=1
      k=split(src, a, "by-name/")
      if (k > 1) { name=a[2]; if (!(name in known)) keep=0 }
      if (mnt == "/vendor" || mnt == "/product" || mnt == "/odm" || mnt == "/cust") keep=0
      if (keep) print
    }' "$f.orig" > "$f"
  AFTER=$(wc -l < "$f")
  log "    $(echo "$f" | sed "s|$MNT||") : $BEFORE → $AFTER 行"
  if [ "$BEFORE" = "$AFTER" ] && [ "$BEFORE" -gt 0 ]; then sed 's/^/      | /' "$f" | head -20; fi
  diff <(grep -v '^[[:space:]]*$' "$f.orig") <(grep -v '^[[:space:]]*$' "$f") | grep '^<' | sed 's/^/      删除: /' || true
done

# ------------------------------------------------ 4. C7 原厂 blob（可选）
if [ "${C7_BLOBS:-0}" = "1" ] && [ -d "$C7_VENDOR_DIR" ]; then
  MODE="${C7_BLOB_MODE:-minimal}"
  log "[4/6] 叠加 C7 原厂 blob（模式 $MODE，不覆盖 donor 同名文件）…"
  C7V="$C7_VENDOR_DIR/vendor"; C7S="$C7_VENDOR_DIR/system"
  ADDED=0; KEPT=0

  put() {   # put <src> <dst>
    [ -e "$1" ] || return 0
    if [ -e "$2" ] || [ -L "$2" ]; then KEPT=$((KEPT+1)); return 0; fi
    mkdir -p "$(dirname "$2")"; cp -a "$1" "$2" 2>/dev/null && ADDED=$((ADDED+1))
    return 0
  }
  # 硬件相关、donor 一定没有的东西：原厂配置目录整棵搬，库按白名单搬。
  for d in etc firmware bhy_firmware; do
    [ -d "$C7V/$d" ] || continue
    while IFS= read -r f; do put "$f" "$MNT/system/vendor/${f#$C7V/}"; done < <( find "$C7V/$d" -type f 2>/dev/null )
  done
  if [ "$MODE" = "full" ]; then
    while IFS= read -r f; do put "$f" "$MNT/system/vendor/${f#$C7V/}"; done < <( find "$C7V/lib" "$C7V/lib64" "$C7V/bin" -type f 2>/dev/null )
    [ -d "$C7S" ] && while IFS= read -r f; do put "$f" "$MNT/system/${f#$C7S/}"; done < <( find "$C7S" -type f 2>/dev/null )
  else
    for f in lib/hw/sensors.msm8953.so lib64/hw/sensors.msm8953.so \
             lib/hw/vendor.samsung.hardware.camera.provider@2.4-impl.so \
             lib64/hw/vendor.samsung.hardware.camera.provider@2.4-impl.so \
             lib/vendor.samsung.hardware.camera.provider@2.4.so \
             lib64/vendor.samsung.hardware.camera.provider@2.4.so \
             lib/libmm-qcamera.so lib64/libmm-qcamera.so \
             lib/libTfa9897.so lib64/libTfa9897.so lib/libtfa9897.so lib64/libtfa9897.so \
             lib/libril.so lib/librilutils.so lib64/libril.so lib64/librilutils.so; do
      put "$C7V/$f" "$MNT/system/vendor/$f"
    done
  fi
  # 白名单：与 C7 硬件强绑定，必须用原厂（覆盖 donor 同名）
  for f in etc/mixer_paths.xml etc/mixer_paths_mtp.xml etc/audio_platform_info.xml \
           etc/Tfa9897.cnt etc/gps.conf; do
    if [ -e "$C7V/$f" ]; then
      mkdir -p "$(dirname "$MNT/system/vendor/$f")"; cp -af "$C7V/$f" "$MNT/system/vendor/$f"
    fi
  done
  for d in etc/camera etc/wifi firmware/wlan; do
    [ -d "$C7V/$d" ] || continue
    rm -rf "$MNT/system/vendor/$d"; mkdir -p "$MNT/system/vendor/$d"
    cp -a "$C7V/$d/." "$MNT/system/vendor/$d/"
  done
  # HIDL 1.0 base shim（三星 8.0 时代的库需要）
  for dir in lib lib64; do
    tgt="$MNT/system/vendor/$dir/libhidlbase.so"
    lnk="$MNT/system/vendor/$dir/android.hidl.base@1.0.so"
    if [ -e "$tgt" ] && [ ! -e "$lnk" ]; then ln -s libhidlbase.so "$lnk"; fi
  done
  log "    新增 $ADDED 个 C7 文件（donor 已有 $KEPT 个同名，保留 donor 版本）"
else
  log "[4/6] 跳过 C7 blob 叠加（C7_BLOBS=${C7_BLOBS:-0}）"
fi

# ------------------------------------------------ 5. 属性（可选）
if [ "${PATCH_PROPS:-0}" = "1" ]; then
  log "[5/6] 改写 build.prop 设备身份 …"
  patch_props() {
    local p="$1"; [ -f "$p" ] || return 0
    sed -i -E \
      -e "s|^ro\.product\.(system\.)?device=.*|ro.product.device=$DEVICE|" \
      -e "s|^ro\.product\.(system\.)?name=.*|ro.product.name=$DEVICE_NAME|" \
      -e "s|^ro\.product\.(system\.)?model=.*|ro.product.model=$DEVICE_MODEL|" \
      -e "s|^ro\.product\.(system\.)?brand=.*|ro.product.brand=$DEVICE_BRAND|" \
      -e "s|^ro\.product\.(system\.)?manufacturer=.*|ro.product.manufacturer=$DEVICE_BRAND|" \
      "$p"
  }
  for p in "$MNT/system/build.prop" "$MNT/system/system_ext/etc/build.prop" \
           "$MNT/system/product/etc/build.prop" "$MNT/system/vendor/build.prop" "$MNT/system/etc/prop.default"; do
    patch_props "$p"
  done
  grep -q "SM-C7000 port" "$MNT/system/vendor/build.prop" 2>/dev/null || {
    { echo; echo "# SM-C7000 (c7ltechn) port — c7ltechn-los17";
      echo "ro.sf.lcd_density=420"; } >> "$MNT/system/vendor/build.prop"
  }
else
  log "[5/6] 保留 donor 的设备身份（PATCH_PROPS=0）"
fi

# ------------------------------------------------ 6. 收尾
log "[6/6] 卸载 + 一致性检查 …"
sync; umount "$MNT"; trap - EXIT
e2fsck -f -y "$SYS_IMG" >/dev/null 2>&1 || warn "e2fsck 报告问题（只读元数据常见，一般无碍）"
tune2fs -c 0 -i 0 "$SYS_IMG" >/dev/null 2>&1 || true
log "system 镜像就绪: $SYS_IMG ($(du -h --apparent-size "$SYS_IMG" | cut -f1))"
log "下一步: 40-make-bootimg.sh"
