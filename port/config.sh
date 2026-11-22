#!/bin/bash
# =============================================================================
#  config.sh — LineageOS 17.1 (Android 10) 移植工程 for Samsung Galaxy C7
#              SM-C7000 / c7ltechn (MSM8953)
# =============================================================================
#  思路（与 C7ROM 的 LOS22.2 工程一致）：不编译 Android 源码，取同 SoC
#  (MSM8953, 骁龙625) 的现成 LineageOS 17.1 包包作为 donor，把 C7 的内核
#  (Linux 4.9.337 + C7 板级 DTS/驱动) 装进去，重新打成可刷镜像。
# =============================================================================
set -euo pipefail

# ---------- 目录 ----------
PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$PROJ_ROOT/tools"
WORK="${WORK:-$PROJ_ROOT/work}"
OUT="$PROJ_ROOT/out"
LOG="$PROJ_ROOT/logs"
mkdir -p "$WORK" "$OUT" "$LOG"

# ---------- 目标设备 ----------
DEVICE=c7ltechn
DEVICE_MODEL=SM-C7000
DEVICE_BRAND=samsung
DEVICE_NAME=c7ltezc
STOCK_BUILD=C7000ZCS3CRJ1          # 基线原厂固件 Android 8.0（仅作 blob 来源）

# ---------- 移植目标 ----------
LOS_VERSION=17.1                   # LineageOS 17.1 = Android 10 (API 29)
ANDROID_VER=10
ANDROID_API=29
PORT_TAG="lineage-${LOS_VERSION}-c7ltechn-port"

# ---------- Donor：红米 Note 4 (mido) LineageOS 17.1 ----------
# 同 SoC（MSM8953），非 Treble 布局（vendor 在 system 内），与 C7 的分区习惯一致。
DONOR_DEVICE=mido
DONOR_NAME="${DONOR_NAME:-lineage-17.1-20200505-UNOFFICIAL-mido.zip}"
DONOR_URL="${DONOR_URL:-https://sourceforge.net/projects/lineageos-17-1/files/mido/${DONOR_NAME}/download}"
GH_PROXY="${GH_PROXY:-}"           # 可选：https://gh-proxy.com/ 这类 github 代理

# ---------- C7 侧素材 ----------
# 原厂 vendor/system 闭源 blob 树（可选；没有也能出"能开机"的第一版）
C7_VENDOR_TARBALL="${C7_VENDOR_TARBALL:-https://codeload.github.com/AwdndWindowsServer/c7ltechn-blobs/tar.gz/refs/heads/main}"
C7_VENDOR_DIR="${C7_VENDOR_DIR:-$WORK/vendor-src/vendor/samsung/c7ltechn/proprietary}"
C7_BLOBS="${C7_BLOBS:-1}"          # 1 = 把 C7 原厂 blob 叠进 system（缺 blob 时自动降级为 0）

# ---------- C7 内核（4.9.337）----------
# 目录内需有 kernel(Image.gz-dtb) 与 dtb(msm8953-c7ltechn.dtb)；由 kernel.yml 产出
C7_KERNEL_DIR="${C7_KERNEL_DIR:-$WORK/c7-kernel}"

# ---------- C7 分区参数（PIT dump 实测，单位字节）----------
PART_BOOT_SIZE=33554432            # 32 MiB
PART_RECOVERY_SIZE=33554432        # 32 MiB
PART_SYSTEM_SIZE=3774873600        # 3.52 GiB
PART_CACHE_SIZE=209715200          # 200 MiB
PART_PERSIST_SIZE=33554432
PART_MODEM_SIZE=100663296
PART_APNHLOS_SIZE=33554432
PART_DSP_SIZE=16777216
PART_EFS_SIZE=16777216
PART_USERDATA_SIZE=25769803776     # 24 GiB（参考值）

SYSTEM_IMG_SIZE=${SYSTEM_IMG_SIZE:-$((PART_SYSTEM_SIZE - 4194304))}

# ---------- boot.img 头部参数（三星 aboot，v0 布局）----------
BOOT_PAGESIZE=2048
BOOT_BASE=0x80000000
BOOT_KERNEL_ADDR=$((BOOT_BASE + 0x00008000))   # 0x80008000
BOOT_RAMDISK_ADDR=$((BOOT_BASE + 0x01000000))  # 0x81000000
BOOT_TAGS_ADDR=$((BOOT_BASE + 0x00000100))     # 0x80000100
# QCDT 表里 C7 的 msm-id / board-id（DTS: qcom,msm-id=<293 ..>, qcom,board-id=<8 4>,<8 3>)
QCDT_MSM_ID=293
QCDT_BOARD_ID=8
QCDT_SUBTYPES="${QCDT_SUBTYPES:-0 3 4}"

# ---------- 原厂分区路径 ----------
BYNAME=/dev/block/bootdevice/by-name

# ---------- 日志 ----------
if [ -t 1 ]; then
  C_INFO=$'\033[1;36m'; C_WARN=$'\033[1;33m'; C_ERR=$'\033[1;31m'; C_END=$'\033[0m'
else
  C_INFO=""; C_WARN=""; C_ERR=""; C_END=""
fi
log()  { echo "${C_INFO}[c7los17]${C_END} $*"; }
warn() { echo "${C_WARN}[WARN ]${C_END} $*"; }
die()  { echo "${C_ERR}[FATAL]${C_END} $*" >&2; exit 1; }

export PATH="$PATH:/usr/sbin:/sbin"

# 下载（支持可用时自动走代理；不覆盖已存在的完整文件）
fetch() {
  local url="$1" out="$2"
  [ -s "$out" ] && { log "已存在: $(basename "$out")"; return 0; }
  local try_url="$url"
  if ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 -C - -o "$out.part" "$try_url"; then
    [ -n "$GH_PROXY" ] || die "下载失败: $url"
    warn "直连失败，改用代理 $GH_PROXY"
    curl -fL --retry 3 --connect-timeout 20 -o "$out.part" "${GH_PROXY}${url}" || die "下载失败: $url"
  fi
  mv "$out.part" "$out"
}
