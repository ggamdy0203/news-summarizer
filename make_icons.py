"""PWA 아이콘 생성 — 192x192, 512x512 PNG"""
import struct, zlib, math

def make_png(size):
    # 짙은 남색 배경 + 흰색 신문 아이콘
    bg = (42, 77, 143)      # #2a4d8f
    fg = (255, 255, 255)    # white
    acc = (251, 191, 36)    # amber

    pixels = []
    cx, cy = size // 2, size // 2
    r = size * 0.42

    for y in range(size):
        row = []
        for x in range(size):
            # 둥근 사각형 배경
            pad = size * 0.12
            rx = size * 0.22
            dx = max(abs(x - cx) - (cx - pad - rx), 0)
            dy = max(abs(y - cy) - (cy - pad - rx), 0)
            in_bg = (dx*dx + dy*dy) <= rx*rx

            if not in_bg:
                row += [0, 0, 0, 0]
                continue

            # 신문 모양 — 가로선 3개
            rel_x = (x - cx) / r
            rel_y = (y - cy) / r

            # 제목 굵은 선
            if -0.55 < rel_x < 0.55 and -0.55 < rel_y < -0.35:
                row += [*fg, 255]
            # 본문 선 1
            elif -0.55 < rel_x < 0.55 and -0.18 < rel_y < -0.06:
                row += [*fg, 255]
            # 본문 선 2
            elif -0.55 < rel_x < 0.00 and 0.08 < rel_y < 0.20:
                row += [*fg, 255]
            # 본문 선 3
            elif -0.55 < rel_x < 0.55 and 0.34 < rel_y < 0.46:
                row += [*fg, 255]
            # 악센트 점 (우하)
            elif 0.15 < rel_x < 0.55 and 0.08 < rel_y < 0.30:
                row += [*acc, 255]
            else:
                row += [*bg, 255]
        pixels.append(row)

    # PNG 인코딩
    def pack_chunk(tag, data):
        c = zlib.crc32(tag + data) & 0xffffffff
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', c)

    raw = b''
    for row in pixels:
        raw += b'\x00' + bytes(row)

    ihdr = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(raw, 9)

    return (
        b'\x89PNG\r\n\x1a\n' +
        pack_chunk(b'IHDR', ihdr) +
        pack_chunk(b'IDAT', idat) +
        pack_chunk(b'IEND', b'')
    )

import os
base = os.path.dirname(os.path.abspath(__file__))
for size, name in [(192, 'icon-192.png'), (512, 'icon-512.png')]:
    with open(os.path.join(base, name), 'wb') as f:
        f.write(make_png(size))
    print(f'{name} 생성 완료 ({size}x{size})')
