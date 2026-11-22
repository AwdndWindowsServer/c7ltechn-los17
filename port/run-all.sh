#!/bin/bash
# =============================================================================
#  run-all.sh — 一条命令跑完：donor 解包 → system 组装 → boot → 卡刷包 → 体检
#  用法: sudo bash port/run-all.sh
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$ROOT"
[ "$(id -u)" = "0" ] || echo "[提示] 组装镜像需要 root（loop 挂载），下面若无权限会失败"

bash port/20-unpack.sh
bash port/30-assemble-system.sh
bash port/40-make-bootimg.sh
MAKE_ODIN="${MAKE_ODIN:-0}" bash port/50-make-zip.sh

if [ -f tools/audit-image.py ] && [ -f work/build/system.img ]; then
  echo "[体检] python3 tools/audit-image.py work/build/system.img"
  python3 tools/audit-image.py work/build/system.img || echo "[体检] 有告警，见上"
fi

echo
echo "产物："
ls -lh out/ | sed 's/^/  /'
