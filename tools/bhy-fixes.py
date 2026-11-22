#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bhy-fixes.py — 把三星 3.18 的 Bosch BHI 传感器中枢驱动改到 Linux 4.9 上。**幂等**。

  用法: python3 tools/bhy-fixes.py [内核树路径]      # 默认 work/kernel-4.9

只有两类差异（都是两条老 API）：

  ① IIO ring buffer：3.18 是手写 `iio_kfifo_allocate(indio_dev)` +
     `iio_buffer_register(indio_dev, chans, n)` + `->buffer/->setup_ops`；
     4.9 把这套收进了 `iio_triggered_buffer_setup()/cleanup()`。
     （实测报错：iio_kfifo_allocate 参数过多、struct iio_buffer 不完整、
       iio_buffer_register/unregister 隐式声明）

  ② `sensors_register()` 的第一个参数在 3.18 是 `struct device **`（我们要传
     `&client_data->acc_device`），而 bhy 直接传了 `struct device *`。
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "work", "kernel-4.9")
CORE = os.path.join(K, "drivers/misc/bhy/bhy_core.c")
HDR = os.path.join(K, "drivers/misc/bhy/bhy_core.h")


def fix_iio_ring():
    txt = open(CORE).read()
    if "iio_triggered_buffer_setup" in txt:
        return "已经是 4.9 写法，跳过"
    m = re.search(r"\tring = iio_kfifo_allocate\(client_data->indio\);.*?iio_device_free\(client_data->indio\);\n",
                  txt, re.S)
    if not m:
        raise SystemExit("找不到 BHY 的 IIO ring 代码块，请人工确认")
    new = (
        "\t/* C7ROM: 4.9 用 iio_triggered_buffer_setup() 取代手写 kfifo ring\n"
        "\t *（老的 iio_kfifo_allocate(dev)/iio_buffer_register()/->buffer/->setup_ops\n"
        "\t *  在 4.9 里已经没有了）*/\n"
        "\tret = iio_triggered_buffer_setup(client_data->indio, NULL, NULL, NULL);\n"
        "\tif (ret)\n"
        "\t\tgoto err_config_ring;\n"
        "\n"
        "\tret = iio_device_register(client_data->indio);\n"
        "\tif (ret)\n"
        "\t\tgoto err_register_device;\n"
        "\n"
        "\tdev_set_drvdata(&client_data->indio->dev, client_data);\n"
        "\n"
        "\treturn 0;\n"
        "\n"
        "err_register_device:\n"
        "\tiio_triggered_buffer_cleanup(client_data->indio);\n"
        "err_config_ring:\n"
        "\tiio_device_free(client_data->indio);\n"
    )
    txt = txt[:m.start()] + new + txt[m.end():]
    # ring 局部变量与 setup_ops 不再使用（-Werror 下 unused 会直接失败）
    txt = txt.replace("\tstruct iio_buffer *ring;\n", "")
    txt = re.sub(r"static const struct iio_buffer_setup_ops ssp_iio_ring_setup_ops = \{.*?\n\};\n\n",
                 "", txt, flags=re.S)
    open(CORE, "w").write(txt)
    return "IIO ring 已改成 iio_triggered_buffer_setup()"


def fix_kconfig():
    """BHY 用 IIO 的 triggered buffer，而 IIO_TRIGGERED_BUFFER 是无提示的 tristate
    （只能被 select），三星原来的 defconfig 是靠别的驱动带进来的。这里让
    SENSORS_BHI 自己 select，保证任何配置下都能编过。"""
    p = os.path.join(K, "drivers/misc/bhy/Kconfig")
    txt = open(p).read()
    if "select IIO_TRIGGERED_BUFFER" in txt:
        return 0
    old = "\tdepends on I2C\n"
    if old not in txt:
        raise SystemExit("bhy/Kconfig 里找不到 depends on I2C")
    txt = txt.replace(old, old + "\tselect IIO_BUFFER\n\tselect IIO_TRIGGERED_BUFFER\n", 1)
    open(p, "w").write(txt)
    return 1


def fix_iio_include():
    """4.9 的 triggered buffer API 在 linux/iio/triggered_buffer.h 里。"""
    txt = open(HDR).read()
    inc = "#include <linux/iio/triggered_buffer.h>"
    if inc in txt:
        return 0
    anchor = "#include <linux/iio/buffer.h>"
    if anchor not in txt:
        raise SystemExit("bhy_core.h 里找不到 iio 头锚点")
    txt = txt.replace(anchor, anchor + "\n" + inc, 1)
    open(HDR, "w").write(txt)
    return 1


def fix_sensors_register():
    txt = open(CORE).read()
    n = 0
    def repl(m):
        nonlocal n
        if m.group(1).startswith("&"):
            return m.group(0)
        n += 1
        return "sensors_register(&%s," % m.group(1)
    txt = re.sub(r"sensors_register\(([^,]+),", repl, txt)
    if n:
        open(CORE, "w").write(txt)
    return "sensors_register 传参修正 %d 处" % n


def main():
    if not os.path.isfile(CORE):
        raise SystemExit("找不到 %s（先跑 tools/bhy-sensorhub-setup.sh）" % CORE)
    print("内核树: %s\n" % K)
    print("[1/4] IIO ring：", fix_iio_ring())
    print("[2/4] IIO 头：", "已补" if fix_iio_include() else "已存在")
    print("[3/4] bhy/Kconfig select IIO：", "已加" if fix_kconfig() else "已存在")
    print("[4/4] sensors_register：", fix_sensors_register())
    print("\n完成（幂等，可重复运行）")


if __name__ == "__main__":
    main()
