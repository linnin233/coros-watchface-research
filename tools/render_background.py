#!/usr/bin/env python3
"""把中文标签画进表盘背景图。

COROS 的 config.txt 没有文字标签字段，所以标签只能烧进背景图。
本脚本按 390x390 基准坐标绘制，并输出三种尺寸：
  390x390   1-bit palette -> watchface_390x390/background.png
  800x800   RGBA          -> watchface_800x800/background.png
  961x961   RGBA          -> custom/custom_bg.png

usage:
    python3 render_background.py --labels "日期:116,步数:156,心率:196" \
        --font /usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc \
        --size 24 --x 62 --out /tmp/bg
"""

import argparse
import io
import os

from PIL import Image, ImageDraw, ImageFont

BASE = 390


def render(labels, font_path, size, x, scale):
    s = scale / BASE
    img = Image.new('RGB', (scale, scale), (0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, max(1, int(size * s)))
    for text, yc in labels:
        d.text((x * s, yc * s), text, font=font, fill=(255, 255, 255), anchor='lm')
    return img


def png_1bit(img):
    """生成 1-bit palette PNG（colortype 3），与官方模板一致。"""
    gray = img.convert('L')
    bw = gray.point(lambda v: 255 if v > 128 else 0, 'L')
    p = Image.new('P', img.size, 0)
    p.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    white = Image.new('P', img.size, 1)
    white.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    p.paste(white, (0, 0), mask=bw)
    b = io.BytesIO()
    p.save(b, format='PNG', bits=1)
    return b.getvalue()


def png_rgba(img):
    b = io.BytesIO()
    img.convert('RGBA').save(b, format='PNG')
    return b.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--labels', required=True, help='标签:行中心y,用逗号分隔')
    ap.add_argument('--font', default='/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc')
    ap.add_argument('--size', type=int, default=24, help='390 基准下的字号')
    ap.add_argument('--x', type=int, default=62, help='标签左边缘 x')
    ap.add_argument('--out', default='/tmp/bg', help='输出前缀')
    args = ap.parse_args()

    labels = []
    for item in args.labels.split(','):
        text, yc = item.rsplit(':', 1)
        labels.append((text, int(yc)))

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or '.', exist_ok=True)

    with open(args.out + '_390.png', 'wb') as f:
        f.write(png_1bit(render(labels, args.font, args.size, args.x, 390)))
    with open(args.out + '_800.png', 'wb') as f:
        f.write(png_rgba(render(labels, args.font, args.size, args.x, 800)))
    with open(args.out + '_961.png', 'wb') as f:
        f.write(png_rgba(render(labels, args.font, args.size, args.x, 961)))

    print(f'written {args.out}_390.png / _800.png / _961.png')


if __name__ == '__main__':
    main()
