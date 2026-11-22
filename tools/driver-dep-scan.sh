#!/bin/bash
# driver-dep-scan.sh — 估算三星 3.18 驱动移植到 4.9 的代价
# 对每个候选驱动：抽出它的 #include <...>，逐个检查头文件在 4.9 树里是否存在，
# 列出"缺的头文件"数量。缺得越少，越好搬。
# 用法: bash tools/driver-dep-scan.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
TB="$ROOT/work/samsung-msm8953-3.18.tar.gz"
K="$ROOT/work/kernel-4.9"
D=android_kernel_samsung_msm8953-lineage-16.0
TMP=$(mktemp -d); trap 'rm -rf $TMP' EXIT

CANDIDATES=(
 "drivers/battery/sm5705_charger.c|SM5705 充电器"
 "drivers/battery/sm5705_fuelgauge.c|SM5705 电量计"
 "drivers/battery/sm5705_charger_oper.c|SM5705 charger_oper"
 "drivers/hwmon/sec_thermistor.c|热敏电阻"
 "drivers/nfc/ese_p3.c|eSE P3"
 "drivers/nfc/pn547.c|NFC PN547/548"
 "drivers/fingerprint/vfs7xxx.c|指纹 VFS7xxx"
 "drivers/misc/bhy/bhy_core.c|BHI 中枢 core"
 "drivers/sensors/sensors_core.c|传感器框架 core"
)
printf "%-26s %6s %6s  %s\n" "驱动" "行数" "缺头文件" "缺哪些（前 6 个）"
for c in "${CANDIDATES[@]}"; do
  f="${c%%|*}"; desc="${c##*|}"
  tar xzOf "$TB" "$D/$f" > "$TMP/x.c" 2>/dev/null || { printf "%-26s %6s\n" "$desc" "不存在"; continue; }
  lines=$(wc -l < "$TMP/x.c")
  miss=(); total=0
  while read -r h; do
    total=$((total+1))
    [ -f "$K/include/$h" ] || [ -f "$K/arch/arm64/include/$h" ] || miss+=("$h")
  done < <(grep -oE '#include <[^>]+>' "$TMP/x.c" | sed -E 's/#include <(.*)>/\1/' | grep -vE '^(asm|linux/compiler|generated)/' | sort -u)
  printf "%-26s %6s %6s  %s\n" "$desc" "$lines" "${#miss[@]}" "$(printf '%s ' "${miss[@]:0:6}" | cut -c1-80)"
done
