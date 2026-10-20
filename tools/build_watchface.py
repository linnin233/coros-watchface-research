#!/usr/bin/env python3
"""从官方模板 zip 生成自定义表盘 zip。

做两件事：
  1. 替换背景资源（三处，见 docs/REPORT.md 第 39.3 节）
  2. 按 JSON 覆盖 config.txt 里的段值

usage:
    python3 build_watchface.py \
        --template template.zip \
        --bg /tmp/bg \
        --config config.json \
        --out my_watchface.zip

config.json 形如:
    {
      "step_rect": "{20,138,360,172,left|vcenter}",
      "step_font": "40x40"
    }
"""

import argparse
import json
import re
import zipfile

BG_TARGETS = {
    'watchface_390x390/background.png': '_390.png',
    'watchface_800x800/background.png': '_800.png',
    'custom/custom_bg.png': '_961.png',
}


def patch_cfg(text, repl):
    out = []
    for line in text.splitlines():
        m = re.match(r'^\[([A-Za-z0-9_]+)\]\s*=(.*)$', line.strip())
        if m and m.group(1) in repl:
            out.append(f'[{m.group(1)}]={repl[m.group(1)]}')
        else:
            out.append(line)
    return '\r\n'.join(out) + '\r\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--template', required=True, help='从 App 下载的模板 zip')
    ap.add_argument('--bg', help='render_background.py 的输出前缀，不给则不换背景')
    ap.add_argument('--config', help='config 覆盖 JSON')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    repl = {}
    if args.config:
        with open(args.config, encoding='utf-8') as f:
            repl = json.load(f)

    bg_data = {}
    if args.bg:
        for target, suffix in BG_TARGETS.items():
            with open(args.bg + suffix, 'rb') as f:
                bg_data[target] = f.read()

    with zipfile.ZipFile(args.template) as zin, \
            zipfile.ZipFile(args.out, 'w', zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            data = zin.read(it.filename)
            if it.filename in bg_data:
                data = bg_data[it.filename]
            elif it.filename == 'watchface_390x390/config.txt' and repl:
                data = patch_cfg(data.decode('gbk'), repl).encode('gbk')
            zout.writestr(it, data)

    print('written', args.out)


if __name__ == '__main__':
    main()
