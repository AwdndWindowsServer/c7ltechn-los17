#!/bin/bash
# kernel-port-headers.sh — 编译驱动的"缺头文件"自动补全循环
#
# 三星驱动移植到 4.9 时最常见的阻塞就是缺少三星私有头文件。
# 本脚本反复编译目标目录，从三星 3.18 tarball 里把缺的头文件抓到 4.9 树里，
# 直到不再出现 "fatal error: xxx: No such file or directory"（或达到上限）。
#
# 用法: bash tools/kernel-port-headers.sh <目标目录/make target> [最大轮数]
set -uo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
TARGET="${1:-drivers/video/fbdev/msm/samsung/}"
MAX="${2:-25}"
K="$ROOT/work/kernel-4.9"
TB="$ROOT/work/samsung-msm8953-3.18.tar.gz"
D=android_kernel_samsung_msm8953-lineage-16.0
cd "$K"
for i in $(seq 1 "$MAX"); do
  out=$(make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
        CROSS_COMPILE_ARM32=arm-linux-gnueabi- "$TARGET" 2>&1)
  hdr=$(echo "$out" | grep -oE "fatal error: [^:]+: No such file" | head -1 | sed 's/fatal error: //;s/: No such file//')
  if [ -z "$hdr" ]; then
    n=$(echo "$out" | grep -c "error:")
    echo "[$i] 没有缺头文件了（当前 error 数: $n）"
    echo "$out" | grep -E "error:" | sed 's|.*/samsung/||' | sort | uniq -c | sort -rn | head -15
    exit 0
  fi
  case "$hdr" in
    linux/*|asm/*|mach/*|media/*|sound/*|linux/../*)
      src="$D/include/$hdr"; dst="$K/include/$hdr" ;;
    *) src="$D/include/linux/$hdr"; dst="$K/include/linux/$hdr" ;;
  esac
  # 先试 include/，再试内核树里同名文件
  if tar tzf "$TB" "$D/include/$hdr" >/dev/null 2>&1; then
    src="$D/include/$hdr"; dst="$K/include/$hdr"
  elif tar tzf "$TB" "$D/include/uapi/$hdr" >/dev/null 2>&1; then
    src="$D/include/uapi/$hdr"; dst="$K/include/uapi/$hdr"
  elif tar tzf "$TB" "$D/$hdr" >/dev/null 2>&1; then
    src="$D/$hdr"; dst="$K/$hdr"
  else
    echo "[$i] ❌ 缺头文件 $hdr —— 三星 3.18 树里也没有，需要写 shim"
    exit 2
  fi
  mkdir -p "$(dirname "$dst")"
  tar xzOf "$TB" "$src" > "$dst"
  echo "[$i] 补入 $hdr  <- $src"
done
echo "达到轮数上限"
