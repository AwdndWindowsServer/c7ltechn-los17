#!/bin/bash
# =============================================================================
#  c7-nvbackup.sh — 三星 Galaxy C7 (SM-C7000/c7ltechn) 刷机前分区备份 / 恢复
#
#  用法：
#    bash tools/c7-nvbackup.sh list                    # 看设备上有哪些分区（只读）
#    bash tools/c7-nvbackup.sh backup [输出目录]        # ★ 刷机前跑这个
#    bash tools/c7-nvbackup.sh restore <备份目录>       # 危险：从备份写回分区
#    bash tools/c7-nvbackup.sh dry-run                 # 不连设备，只打印计划做的事
#
#  为什么需要它：
#    EFS 里有 IMEI、MODEMST1/2 里有基带校准、PERSIST 里有传感器/触摸校准 ——
#    这三样**丢了不可恢复**（除非你有本机专属的备份）。本工程的移植包只写
#    boot + system，正常情况下不会碰它们；但任何"清 data / 刷四件套 / 手滑"
#    都可能波及。备份成本几十 MB，恢复成本一条命令。
#
#  在哪里跑：
#    **推荐 TWRP 里**（分区没被挂载、adbd 直接是 root）。已开机的系统里也能跑，
#    但需要 root，而且 efs/persist 可能正被挂载（脚本会警告）。
#
#  备份哪些（默认，都是小分区，合计约 200 MiB）：
#    efs / modemst1 / modemst2 / fsg / fsc / persist / param / modem / apnhlos / dsp
#    + boot / recovery（便于回滚刷机前的状态）
#    + 上面这些在 TWRP 里能找到的其它小底层分区（best effort）
#    + 本工程存档的 PIT（分区表本体，用于事后核对）
#  用 --all 才会连 system/cache/userdata 一起备（几个 GB，一般不需要）。
#
#  实现要点：
#    * 优先用 /dev/block/bootdevice/by-name/<名字>；
#    * 找不到 by-name 时回退到**原始 LBA 偏移**（表的来源就是本工程实测的
#      C7000-HONGKONG_CHN_OPEN.pit，Identifier 字段 = mmcblk0pN）；
#    * 数据用 adb exec-out 直接流到本地（不在手机上占空间）；
#    * 每个分区算 sha256 写进 MANIFEST.txt，恢复时逐个校验；
#    * 备份目录里会生成一个自包含的 restore-from-this-dir.sh。
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PIT="$ROOT/stock-ref/C7LTE_CHN_OPEN.pit"
DEV_BY_NAME_CANDIDATES=(
	/dev/block/bootdevice/by-name
	/dev/block/by-name
	/dev/block/platform/soc/7824900.sdhci/by-name
	/dev/block/platform/soc/7824900.sdhci/by-name
)
BLOCKDEV=/dev/block/mmcblk0

# ---------------------------------------------------------------- 分区表
# 来自本工程实测 PIT：名字|起始LBA|扇区数|是否默认备份(1/0)
# （LBA × 512 = 字节偏移；扇区数 × 512 = 分区大小）
PART_TABLE=(
	"sbl1|8192|1024|1"
	"sbl1bak|9216|1024|1"
	"rpm|11264|1024|1"
	"tz|12288|4096|1"
	"aboot|16384|4096|1"
	"modemst1|32768|8192|1"
	"modemst2|40960|8192|1"
	"efs|57344|32768|1"
	"persist|286720|65536|1"
	"dsp|360448|32768|1"
	"modem|393216|196608|1"
	"apnhlos|589824|65536|1"
	"boot|131072|65536|1"
	"recovery|196608|65536|1"
	"bota|262144|16384|1"
	"fota|278528|8192|1"
	"system|688128|7372800|0"
	"cache|8060928|409600|0"
	"userdata|8470528|0|0"
)
# TWRP 里有 by-name、但 PIT 表没给 LBA 的小分区：能读到就备（best effort）
EXTRA_BEST_EFFORT=(fsg fsc ssd devcfg apdp msadp params backup persistent steady keystore config keymaster cmnlib cmnlib64 lksecapp sec)

info()  { printf '\033[1;36m[C7]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
err()   { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; }
die()   { err "$*"; exit 1; }

# ---------------------------------------------------------------- 设备侧访问
ADB=${ADB:-adb}
SU=""            # 空 = 已是 root；否则 "su -c"

dev_sh() {  # 在设备上执行（返回文本）
	$ADB shell "$@" 2>/dev/null
}
dev_root_sh() {
	if [ -n "$SU" ]; then $ADB shell "$SU '$*'" 2>/dev/null; else $ADB shell "$*" 2>/dev/null; fi
}
dev_exec() {  # 二进制安全：把设备上命令的 stdout 流到本地
	if [ -n "$SU" ]; then $ADB exec-out $SU "$1" 2>/dev/null; else $ADB exec-out sh -c "$1" 2>/dev/null; fi
	# 注：$1 必须整体作为一个参数传给 su -c，否则 su 只拿到第一个词
}

preflight() {
	command -v "$ADB" >/dev/null || die "找不到 adb，请装 android-tools-adb 并把 adb 放进 PATH"
	local state
	state=$($ADB get-state 2>/dev/null) || die "没有连上设备（adb devices 看一下；TWRP 里也能用）"
	[ "$state" = "device" ] || die "设备状态是 '$state'（不是 device），先在手机上授权 USB 调试"
	local id
	id=$(dev_sh id)
	case "$id" in
		*uid=0*) SU="" ;;
		*)
			if dev_sh "su -c id" | grep -q "uid=0"; then SU="su -c"
			else die "设备上没有 root。请在 **TWRP** 里跑这个脚本（TWRP 的 adbd 默认 root）"; fi ;;
	esac
	local twrp dev prop
	twrp=$(dev_sh getprop ro.twrp.version)
	dev=$(dev_sh getprop ro.product.device)
	if [ -n "$twrp" ]; then
		info "设备：TWRP $twrp（$dev）  —— 分区未挂载，最安全"
	else
		prop=$(dev_sh getprop ro.build.fingerprint)
		warn "设备当前是**已开机的系统**（$prop）"
		warn "efs / persist 可能正被挂载，读出来的可能不是静止状态；能进 TWRP 最好进 TWRP"
		printf '    继续？(yes/N) '; read -r a; [ "$a" = "yes" ] || exit 1
	fi
	[ -n "$dev" ] && [ "$dev" != "c7ltechn" ] && [ "$dev" != "c7lte" ] && \
		warn "ro.product.device=$dev（本工程针对 c7ltechn，分区表按 C7000 的 PIT；请确认机型一致）"
}

find_by_name_dir() {
	local d
	for d in "${DEV_BY_NAME_CANDIDATES[@]}"; do
		if dev_sh "[ -d $d ] && echo ok" | grep -q ok; then echo "$d"; return 0; fi
	done
	return 1
}

human() { awk -v b="$1" 'BEGIN{split("B KiB MiB GiB",u," ");i=1;while(b>=1024&&i<4){b/=1024;i++}printf (i==1?"%d %s":"%.1f %s"),b,u[i]}'; }

# ---------------------------------------------------------------- list
cmd_list() {
	preflight
	local dir; dir=$(find_by_name_dir) || { warn "没有 by-name 目录，改用原始偏移（表来自 PIT）"; }
	echo
	printf '%-14s %-12s %-12s %s\n' "分区" "起始LBA" "大小" "设备节点"
	printf '%s\n' "--------------------------------------------------------------"
	local row name lba sec def size node
	for row in "${PART_TABLE[@]}"; do
		IFS='|' read -r name lba sec def <<<"$row"
		size=$((sec * 512))
		node="-"
		if [ -n "$dir" ]; then
			dev_sh "[ -e $dir/$name ] && echo $dir/$name" | grep -q . && node="$dir/$name"
		fi
		[ "$node" = "-" ] && node="(用 mmcblk0 + skip=$lba)"
		printf '%-14s %-12s %-12s %s\n' "$name" "$lba" "$(human $size)" "$node"
	done
	echo
	info "PIT 存档：$PIT $([ -f "$PIT" ] && echo "(存在，$(stat -c%s "$PIT") B)" || echo "(缺失)")"
}

# ---------------------------------------------------------------- backup
cmd_backup() {
	local out="" all=0 a
	for a in "$@"; do
		case "$a" in
			--all) all=1 ;;
			"") ;;
			*) [ -z "$out" ] && out="$a" ;;
		esac
	done
	[ -n "$out" ] || out="$ROOT/out/nvbackup-$(date +%Y%m%d-%H%M%S)"
	preflight
	mkdir -p "$out" || die "建不了输出目录 $out"
	local dir; dir=$(find_by_name_dir) || dir=""
	[ -n "$dir" ] && info "by-name 目录：$dir" || warn "没有 by-name，全部走原始偏移（PIT）"

	{
		echo "# C7 分区备份清单"
		echo "时间: $(date -Is)"
		echo "设备: $(dev_sh getprop ro.product.device) / $(dev_sh getprop ro.product.model)"
		echo "构建: $(dev_sh getprop ro.build.fingerprint)"
		echo "TWRP: $(dev_sh getprop ro.twrp.version)"
		echo "by-name: ${dir:-（无）}"
		echo "adb: $($ADB version | head -1)"
		echo
		printf '%-14s %-12s %-64s %s\n' "分区" "大小(字节)" "sha256" "文件"
	} > "$out/MANIFEST.txt"

	local n=0 fail=0 total=0 row name lba sec def size src f ok sha got
	for row in "${PART_TABLE[@]}"; do
		IFS='|' read -r name lba sec def <<<"$row"
		[ "$def" = "1" ] || { [ "$all" = "1" ] || continue; }
		size=$((sec * 512)); [ "$size" = "0" ] && size=""     # userdata 长度未知
		src=""; f="$out/$name.img"; ok=0
		if [ -n "$dir" ]; then
			dev_sh "[ -e $dir/$name ] && echo $dir/$name" | grep -q . && { src="$dir/$name"; ok=1; }
		fi
		if [ "$ok" = "0" ] && [ -n "$size" ]; then
			src="$BLOCKDEV (skip=$lba count=$sec)"; ok=1
		fi
		[ "$ok" = "1" ] || { warn "跳过 $name（设备上没有，且表里也没有偏移）"; continue; }

		printf '  → %-12s %s ... ' "$name" "$src"
		if [ -n "$size" ]; then
			dev_exec "dd if=$src bs=4096 count=$((size / 4096)) 2>/dev/null" > "$f"
		else
			dev_exec "dd if=$src bs=4096 2>/dev/null" > "$f"
		fi
		got=$(stat -c%s "$f" 2>/dev/null || echo 0)
		if [ "$got" = "0" ]; then printf '\033[1;31m失败\033[0m\n'; rm -f "$f"; fail=$((fail+1)); continue; fi
		if [ -n "$size" ] && [ "$got" != "$size" ]; then
			warn "大小不符（期望 $size，实得 $got）—— 保留但请留意"
		fi
		sha=$(sha256sum "$f" | awk '{print $1}')
		printf '%s  %s\n' "$(human "$got")" "${sha:0:16}…"
		printf '%-14s %-12s %-64s %s\n' "$name" "$got" "$sha" "$(basename "$f")" >> "$out/MANIFEST.txt"
		n=$((n+1)); total=$((total + got))
	done

	# best effort：TWRP 里能读到的小分区
	if [ -n "$dir" ]; then
		local e p size2 got2 sha2
		for e in "${EXTRA_BEST_EFFORT[@]}"; do
			[ -e "$out/$e.img" ] && continue
			p=$(dev_sh "[ -e $dir/$e ] && echo $dir/$e")
			[ -n "$p" ] || continue
			size2=$(dev_sh "blockdev --getsize64 $p" 2>/dev/null | tr -dc 0-9)
			[ -n "$size2" ] && [ "$size2" -gt 0 ] && [ "$size2" -le 33554432 ] || continue
			printf '  → %-12s (best effort) ... ' "$e"
			dev_exec "dd if=$p bs=4096 2>/dev/null" > "$out/$e.img"
			got2=$(stat -c%s "$out/$e.img" 2>/dev/null || echo 0)
			[ "$got2" = "0" ] && { rm -f "$out/$e.img"; printf '跳过\n'; continue; }
			sha2=$(sha256sum "$out/$e.img" | awk '{print $1}')
			printf '%s  %s\n' "$(human "$got2")" "${sha2:0:16}…"
			printf '%-14s %-12s %-64s %s\n' "$e" "$got2" "$sha2" "$e.img" >> "$out/MANIFEST.txt"
			n=$((n+1)); total=$((total + got2))
		done
	fi

	# PIT 本体（工程存档；恢复时用于核对分区表）
	[ -f "$PIT" ] && cp -f "$PIT" "$out/C7LTE_CHN_OPEN.pit" && \
		echo "PIT 存档: C7LTE_CHN_OPEN.pit" >> "$out/MANIFEST.txt"

	# 自包含恢复脚本
	cat > "$out/restore-from-this-dir.sh" <<'EOS'
#!/bin/bash
# 从这个备份目录恢复 C7 分区。★ 会覆盖设备上的 efs/modemst/persist 等，务必确认。
# 用法: bash restore-from-this-dir.sh [--yes]      # 默认逐个交互确认
set -uo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ADB=${ADB:-adb}; YES=0; [ "${1:-}" = "--yes" ] && YES=1
[ -f "$HERE/MANIFEST.txt" ] || { echo "缺 MANIFEST.txt"; exit 1; }
SU=""; adb shell id 2>/dev/null | grep -q uid=0 || SU="su -c"
bys() { for d in /dev/block/bootdevice/by-name /dev/block/by-name; do adb shell "[ -d $d ]" 2>/dev/null && { echo "$d"; return; }; done; }
DIR=$(bys)
echo "目标设备: $(adb shell getprop ro.product.device 2>/dev/null)  分区目录: ${DIR:-（无，恢复需要 by-name）}"
[ -n "$DIR" ] || { echo "没有 by-name，拒绝恢复（请进 TWRP）"; exit 1; }
grep -E '^[a-z0-9_]+ +[0-9]+ +[0-9a-f]{64}' "$HERE/MANIFEST.txt" | while read -r name size sha file; do
  f="$HERE/$file"
  [ -f "$f" ] || { echo "跳过 $name：缺 $file"; continue; }
  got=$(sha256sum "$f" | awk '{print $1}')
  [ "$got" = "$sha" ] || { echo "!! $name 校验失败（备份文件损坏？） 期望 ${sha:0:12} 实得 ${got:0:12}"; continue; }
  if [ "$YES" != "1" ]; then printf '写回 %-12s (%s) ? (yes/N) ' "$name" "$size"; read -r a; [ "$a" = yes ] || continue; fi
  adb shell "[ -e $DIR/$name ]" 2>/dev/null || { echo "跳过 $name：设备上没有该分区"; continue; }
  echo -n "  dd -> $name ... "
  if [ -n "$SU" ]; then adb exec-out $SU "dd of=$DIR/$name bs=4096 2>/dev/null" < "$f"; else adb exec-out sh -c "dd of=$DIR/$name bs=4096 2>/dev/null" < "$f"; fi
  echo done
done
echo "完成。建议重启到系统确认 IMEI/传感器正常。"
EOS
	chmod +x "$out/restore-from-this-dir.sh"

	echo
	info "备份完成：$n 个分区，共 $(human "$total")"
	info "目录：$out"
	[ "$fail" -gt 0 ] && warn "有 $fail 个分区读取失败（看上面输出）"
	info "把整个目录**再复制一份到电脑/U盘/网盘**——只留手机里不算备份"
	printf '\n恢复（确认无误后再用）：bash tools/c7-nvbackup.sh restore %s\n' "$out"
}

# ---------------------------------------------------------------- restore
cmd_restore() {
	local src="${1:-}"; [ -n "$src" ] || die "用法：bash tools/c7-nvbackup.sh restore <备份目录>"
	[ -f "$src/MANIFEST.txt" ] || die "$src 里没有 MANIFEST.txt，不像本脚本的备份目录"
	preflight
	local dir; dir=$(find_by_name_dir) || die "设备上没有 by-name 目录；恢复请进 TWRP"
	warn "即将把 $src 里的分区**写回设备**。这会覆盖 efs/modemst/persist —— 写错可能失去 IMEI。"
	dev_sh getprop ro.product.device | grep -qE 'c7lte' || warn "目标机型不是 c7lte*，强烈建议停手"
	printf '确认请输入设备代号（c7ltechn / c7lte / c7ltezc）：'; read -r a
	case "$a" in c7ltechn|c7lte|c7ltezc) ;; *) die "输入不符，已中止（什么都没写）";; esac

	local n=0 name size sha file f got
	while read -r name size sha file; do
		case "$name" in \#*|分区|"") continue;; esac
		[ -n "${size:-}" ] && [ -n "${sha:-}" ] || continue
		f="$src/$file"; [ -f "$f" ] || { warn "跳过 $name：缺 $file"; continue; }
		got=$(sha256sum "$f" | awk '{print $1}')
		[ "$got" = "$sha" ] || { warn "跳过 $name：校验失败（备份损坏）"; continue; }
		dev_sh "[ -e $dir/$name ]" | grep -q . || { warn "跳过 $name：设备上没有"; continue; }
		printf '  dd -> %-12s ' "$name"
		dev_exec "dd of=$dir/$name bs=4096 2>/dev/null" < "$f" >/dev/null
		echo "done"; n=$((n+1))
	done < <(grep -E '^[a-z0-9_]+ +[0-9]+ +[0-9a-f]{64}' "$src/MANIFEST.txt")
	info "恢复完成：$n 个分区。建议重启后确认 IMEI（设置→关于手机）与传感器。"
}

# ---------------------------------------------------------------- dry-run
cmd_dryrun() {
	echo "【dry-run】不连设备，只列出默认会备份什么、命令长什么样："
	echo
	local row name lba sec def size
	for row in "${PART_TABLE[@]}"; do
		IFS='|' read -r name lba sec def <<<"$row"
		[ "$def" = "1" ] || continue
		size=$((sec * 512))
		printf '  %-12s %-10s by-name: /dev/block/bootdevice/by-name/%-12s | 回退: mmcblk0 skip=%-8s count=%s\n' \
			"$name" "$(human $size)" "$name" "$lba" "$sec"
	done
	echo
	echo "  默认合计约：$(human $(( (1024+1024+1024+4096+4096+8192+8192+32768+65536+32768+196608+65536+65536+65536+16384+8192) * 512 )))"
	echo "  （--all 才包含 system/cache/userdata，几个 GB）"
	echo
	echo "备份命令形态（二进制安全，不占手机空间）："
	echo "  adb exec-out sh -c 'dd if=/dev/block/bootdevice/by-name/efs bs=4096 count=4096' > efs.img"
}

# ---------------------------------------------------------------- 入口
case "${1:-}" in
	list)    cmd_list ;;
	backup)  cmd_backup "${@:2}" ;;
	restore) cmd_restore "${2:-}" ;;
	dry-run|--dry-run) cmd_dryrun ;;
	*)
		sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
		exit 0 ;;
esac
