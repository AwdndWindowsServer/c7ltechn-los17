@echo off
rem ============================================================================
rem  c7-nvbackup.bat — 三星 Galaxy C7 (SM-C7000 / c7ltechn) 刷机前分区备份/恢复
rem                    Windows 原生批处理版（不需要 Git Bash / WSL）
rem
rem  用法（cmd 里，或直接双击后按提示）：
rem    c7-nvbackup.bat dryrun                不连设备，先看计划（安全）
rem    c7-nvbackup.bat list                  连上设备，列分区（只读）
rem    c7-nvbackup.bat backup [输出目录]      ★ 刷机前跑这个
rem    c7-nvbackup.bat restore <备份目录>     危险：从备份写回分区
rem
rem  依赖：adb 在 PATH（platform-tools）；哈希用系统自带 certutil。
rem  ★ 推荐在 **TWRP** 里跑（分区未挂载、adbd 直接是 root）。
rem  ★ 本脚本在 Linux 侧写的，没在 Windows 上实测过；先跑 dryrun 看输出是否符合预期，
rem    任何一步不对就用 docs/04-刷机指南.md 里的**手工命令**（那些是通用的，一定可用）。
rem ============================================================================
setlocal enabledelayedexpansion
pushd "%~dp0.."
set "ROOT=%CD%"
popd
set "ADB=adb"
rem 名字|起始LBA|扇区数|是否默认备份
set "PART_TABLE=sbl1|8192|1024|1;sbl1bak|9216|1024|1;rpm|11264|1024|1;tz|12288|4096|1;aboot|16384|4096|1;modemst1|32768|8192|1;modemst2|40960|8192|1;efs|57344|32768|1;persist|286720|65536|1;dsp|360448|32768|1;modem|393216|196608|1;apnhlos|589824|65536|1;boot|131072|65536|1;recovery|196608|65536|1;bota|262144|16384|1;fota|278528|8192|1"
set "Q=%PART_TABLE:;=" "%"
set "MODE=%~1"

if /i "%MODE%"=="dryrun"  goto :dryrun
if /i "%MODE%"=="list"    goto :list
if /i "%MODE%"=="backup"  goto :backup
if /i "%MODE%"=="restore" goto :restore
call :usage
exit /b 0

:usage
echo.
echo   c7-nvbackup.bat -- C7 分区备份/恢复（Windows）
echo.
echo     c7-nvbackup.bat dryrun               不连设备，只看计划
echo     c7-nvbackup.bat list                 连上设备，列出分区
echo     c7-nvbackup.bat backup [输出目录]    ★ 备份（默认 %ROOT%\out\nvbackup-^<时间^>）
echo     c7-nvbackup.bat restore ^<备份目录^>   危险：写回分区
echo.
echo   手机先进 TWRP（音量上+Home+电源），插 USB，adb devices 显示 device 再跑。
echo.
exit /b 0

:precheck
"%ADB%" version >nul 2>&1 || (echo [x] 找不到 adb：把 platform-tools 加进 PATH，或把 adb.exe 放到本文件旁边 & exit /b 1)
set "STATE="
for /f "tokens=*" %%S in ('"%ADB%" get-state 2^>nul') do set "STATE=%%S"
if /i not "!STATE!"=="device" (echo [x] 设备状态 "!STATE!" 不是 device：手机上允许 USB 调试，或换线/换 USB2.0 口 & exit /b 1)
set "TWRP="
for /f "tokens=*" %%T in ('"%ADB%" shell getprop ro.twrp.version 2^>nul') do set "TWRP=%%T"
set "DEV="
for /f "tokens=*" %%D in ('"%ADB%" shell getprop ro.product.device 2^>nul') do set "DEV=%%D"
if defined TWRP (echo [C7] 设备：TWRP !TWRP! ^(!DEV!^)  —— 分区未挂载，最安全) else (echo [!] 当前是已开机系统 ^(!DEV!^)：efs/persist 可能正被挂载；能进 TWRP 最好进 TWRP)
exit /b 0

:finddir
set "BYNAME="
for %%P in (/dev/block/bootdevice/by-name /dev/block/by-name) do (
	if not defined BYNAME (
		"%ADB%" shell "[ -d %%P ] && echo ok" 2>nul | findstr /c:"ok" >nul && set "BYNAME=%%P"
	)
)
exit /b 0

rem ---------------------------------------------------------------- dryrun
:dryrun
echo.
echo [dryrun] 默认备份列表（表来自本工程实测的 C7000 PIT；扇区 = 512 B）
echo.
for %%R in ("%Q%") do (
	for /f "tokens=1,2,3,4 delims=|" %%a in (%%R) do (
		if "%%d"=="1" (
			set /a KB=%%c/2
			echo    %%~a   起始LBA=%%~b   大小=%%~c 扇区 ^(约 !KB! KiB^)   by-name: /dev/block/bootdevice/by-name/%%~a
		)
	)
)
echo.
echo   默认合计约 281 MiB（system/cache/userdata 不在默认列表里）
echo   单条命令形态：
echo     adb exec-out sh -c "dd if=/dev/block/bootdevice/by-name/efs bs=4096 count=4096" ^> efs.img
echo.
exit /b 0

rem ---------------------------------------------------------------- list
:list
call :precheck || exit /b 1
call :finddir
echo.
if defined BYNAME (echo [C7] by-name 目录：!BYNAME!) else (echo [!] 没有 by-name；备份会退回 mmcblk0 + 偏移)
echo.
for %%R in ("%Q%") do (
	for /f "tokens=1,2,3,4 delims=|" %%a in (%%R) do (
		set "NM=%%~a"
		set /a KB=%%c/2
		set "HIT="
		if defined BYNAME "%ADB%" shell "[ -e !BYNAME!/!NM! ] && echo ok" 2>nul | findstr /c:"ok" >nul && set "HIT=1"
		if defined HIT (echo    !NM!  约 !KB! KiB   !BYNAME!/!NM!) else (echo    !NM!  约 !KB! KiB   ^(表里有偏移：skip=%%~b count=%%~c^) )
	)
)
echo.
exit /b 0

rem ---------------------------------------------------------------- backup
:backup
set "OUT=%~2"
if "%OUT%"=="" (
	set "STAMP=%DATE:/=-%"
	set "STAMP=!STAMP::=-!"
	set "STAMP=!STAMP:,=-!"
	set "STAMP=!STAMP: =0!"
	set "OUT=%ROOT%\out\nvbackup-!STAMP!"
)
call :precheck || exit /b 1
call :finddir
if not exist "%OUT%" mkdir "%OUT%" || (echo [x] 建不了目录 %OUT% & exit /b 1)
echo [C7] 备份目录：%OUT%
echo.
> "%OUT%\MANIFEST.txt" (
	echo # C7 分区备份清单
	echo 时间: %DATE% %TIME%
	echo 设备: !DEV!
	echo by-name: !BYNAME!
	echo 格式: PART^|名字^|字节^|sha256^|文件
)
set /a N=0
set /a TOTAL=0
for %%R in ("%Q%") do (
	for /f "tokens=1,2,3,4 delims=|" %%a in (%%R) do (
		if "%%d"=="1" (
			set "NM=%%~a"
			set "LBA=%%~b"
			set "SEC=%%~c"
			set "IMG=%OUT%\!NM!.img"
			<nul set /p "=  -^> !NM! ... "
			set "HIT="
			if defined BYNAME "%ADB%" shell "[ -e !BYNAME!/!NM! ] && echo ok" 2>nul | findstr /c:"ok" >nul && set "HIT=1"
			if defined HIT (
				"%ADB%" exec-out sh -c "dd if=!BYNAME!/!NM! bs=4096 count=!SEC! 2>/dev/null" > "!IMG!"
			) else (
				"%ADB%" exec-out sh -c "dd if=/dev/block/mmcblk0 bs=512 skip=!LBA! count=!SEC! 2>/dev/null" > "!IMG!"
			)
			set "SZ=0"
			if exist "!IMG!" for %%Z in ("!IMG!") do set "SZ=%%~zZ"
			if "!SZ!"=="0" (
				echo 失败^(读不到^)
				del /q "!IMG!" 2>nul
			) else (
				set "HASH="
				for /f "tokens=* delims=" %%H in ('certutil -hashfile "!IMG!" SHA256 ^| findstr /r "^[0-9a-f]"') do if not defined HASH set "HASH=%%H"
				if not defined HASH (
					echo 哈希算不出来，丢弃
					del /q "!IMG!" 2>nul
				) else (
					set "HASH=!HASH: =!"
					echo !SZ! 字节  !HASH:~0,16!...
					>>"%OUT%\MANIFEST.txt" echo PART^|!NM!^|!SZ!^|!HASH!^|!NM!.img
					set /a N+=1
					set /a TOTAL+=!SZ!
				)
			)
		)
	)
)
if exist "%ROOT%\stock-ref\C7LTE_CHN_OPEN.pit" copy /y "%ROOT%\stock-ref\C7LTE_CHN_OPEN.pit" "%OUT%\" >nul
echo.
echo [C7] 备份完成：!N! 个分区，共 !TOTAL! 字节
echo [C7] 目录：%OUT%
echo [C7] ★ 把整个目录再复制一份到 U 盘/网盘 —— 只留在手机里不算备份
echo.
echo 恢复（确认无误后再用）：c7-nvbackup.bat restore "%OUT%"
exit /b 0

rem ---------------------------------------------------------------- restore
:restore
set "SRC=%~2"
if "%SRC%"=="" (echo 用法：c7-nvbackup.bat restore ^<备份目录^> & exit /b 1)
if not exist "%SRC%\MANIFEST.txt" (echo [x] %SRC% 里没有 MANIFEST.txt，不是本脚本的备份目录 & exit /b 1)
call :precheck || exit /b 1
call :finddir
if not defined BYNAME (echo [x] 设备没有 by-name 目录；恢复请进 TWRP & exit /b 1)
echo.
echo [!] 即将把 %SRC% 里的分区**写回设备**，会覆盖 efs/modemst/persist。
echo     写错可能永久失去 IMEI。请输入设备代号确认（c7ltechn / c7lte / c7ltezc）：
set "CONF="
set /p "CONF="
if /i not "!CONF!"=="c7ltechn" if /i not "!CONF!"=="c7lte" if /i not "!CONF!"=="c7ltezc" (echo 输入不符，已中止，什么都没写 & exit /b 1)
set /a N=0
for /f "usebackq tokens=1,2,3,4,5 delims=|" %%a in ("%SRC%\MANIFEST.txt") do (
	if /i "%%a"=="PART" (
		set "NM=%%b"
		set "SZ=%%c"
		set "HASH=%%d"
		set "FILE=%%e"
		if not exist "%SRC%\!FILE!" (
			echo   跳过 !NM!：缺 !FILE!
		) else (
			set "H2="
			for /f "tokens=* delims=" %%H in ('certutil -hashfile "%SRC%\!FILE!" SHA256 ^| findstr /r "^[0-9a-f]"') do if not defined H2 set "H2=%%H"
			set "H2=!H2: =!"
			if /i not "!H2!"=="!HASH!" (
				echo   !! !NM! 校验失败^(备份损坏^)，跳过
			) else (
				<nul set /p "=  dd -^> !NM! ... "
				"%ADB%" exec-out sh -c "dd of=!BYNAME!/!NM! bs=4096 2>/dev/null" < "%SRC%\!FILE!" >nul 2>&1
				echo done
				set /a N+=1
			)
		)
	)
)
echo.
echo [C7] 恢复完成：!N! 个分区。重启后到「设置→关于手机」确认 IMEI，并试一下传感器。
exit /b 0
