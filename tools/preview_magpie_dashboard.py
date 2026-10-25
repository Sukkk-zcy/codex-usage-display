"""Render layout previews with the firmware's exact 4-bit antialiased glyphs.

These are host layout previews, not hardware screenshots. Example data is used.
Shapes are supersampled; text uses the firmware's generated glyph bitmaps. Pillow only.
"""
from pathlib import Path
import math
import json
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'preview' / 'magpie_dashboard'
SCALE = 3


def rgb(value):
    return ((value >> 11 & 31) * 255 // 31,
            (value >> 5 & 63) * 255 // 63, (value & 31) * 255 // 31)


BG, CARD, TRACK, MUTED, WHITE, TEAL, LIME, AMBER, RED, BLUE = map(
    rgb, (0x0862, 0x10C4, 0x2166, 0x94F4, 0xEF9E, 0x3F59, 0xCFCB, 0xFD8B, 0xFA8C, 0x6D9F))


class Font:
    def __init__(self, size):
        data = json.loads((ROOT/'tools/dashboard_fonts.json').read_text())[str(size)]
        self.bits = bytes.fromhex(data['pixels'])
        self.glyphs = data['glyphs']
        self.ascent = data['cap_height']

    def width(self, value):
        value = str(value)
        if not value:
            return 0
        advance = right = 0
        for char in value:
            g = self.glyphs[ord(char)-32]
            right = max(right, advance+g[4]+g[1])
            advance += g[3]
        return max(advance, right)

    def draw(self, image, value, x, y, color):
        cursor = int(x)
        for char in str(value):
            offset, width, height, advance, dx, dy = self.glyphs[ord(char) - 32]
            mask = Image.new('L', (max(width, 1), max(height, 1)))
            for i in range(width * height):
                packed = self.bits[offset+i//2]
                alpha = (packed & 15) if i & 1 else packed >> 4
                mask.putpixel((i % width, i // width), alpha*17)
            mask = mask.resize((max(width, 1) * SCALE, max(height, 1) * SCALE), Image.Resampling.NEAREST)
            image.paste(color, ((cursor + dx) * SCALE, (int(y) + dy) * SCALE), mask)
            cursor += advance


FONTS = {n: Font(n) for n in (9, 12, 18, 24)}


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class Preview:
    def __init__(self, page=0, status='LIVE'):
        self.im = Image.new('RGB', (320 * SCALE, 240 * SCALE), BG)
        self.draw = ImageDraw.Draw(self.im)
        self.page = page
        self.header(status)
        self.text('15:48', 14, 213, 12, WHITE)
        for i in range(4):
            if i == page:
                self.box(255 + i * 14, 221, 14, 5, 2, TEAL)
            else:
                self.dot(259 + i * 14, 223, 2, TRACK)

    def box(self, x, y, w, h, radius, color):
        self.draw.rounded_rectangle((x * SCALE, y * SCALE, (x + w - 1) * SCALE, (y + h - 1) * SCALE), radius * SCALE, fill=color)

    def dot(self, x, y, radius, color):
        self.draw.ellipse(((x - radius) * SCALE, (y - radius) * SCALE, (x + radius) * SCALE, (y + radius) * SCALE), fill=color)

    def text(self, value, x, y, size=9, color=MUTED):
        FONTS[size].draw(self.im, value, round(x), y, color)

    def center(self, value, x, y, size=9, color=MUTED):
        self.text(value, x - FONTS[size].width(value) // 2, y, size, color)

    def right(self, value, x, y, size=9, color=MUTED):
        self.text(value, x - FONTS[size].width(value), y, size, color)

    def fit(self, value, width, size=9):
        if FONTS[size].width(value) <= width:
            return value
        while value and FONTS[size].width(value + '..') > width:
            value = value[:-1]
        return value + '..'

    def header(self, status):
        self.dot(17, 22, 5, TEAL)
        self.dot(27, 16, 3, LIME)
        self.dot(28, 27, 2, TEAL)
        self.text('magpie', 40, 10, 12, WHITE)
        width = FONTS[9].width(status) + 30
        left = 308 - width
        self.box(left, 10, width, 25, 12, CARD)
        color = TEAL if status == 'LIVE' else AMBER
        self.dot(left + 12, 22, 5, mix(CARD, color, .22))
        self.dot(left + 12, 22, 2, color)
        self.text(status, left + 23, 16, 9, color)

    def arc(self, start, end, color, radius=65, width=10):
        self.draw.arc(((85 - radius) * SCALE, (124 - radius) * SCALE,
                       (85 + radius) * SCALE, (124 + radius) * SCALE),
                      start + 90, end + 90, fill=color, width=width * SCALE)

    def ring(self, value, caption='QUOTA', low=False):
        # Pillow draws its stroke inside the radius; TFT_eSPI uses outer/inner radii.
        for angle in range(30, 330):
            self.arc(angle, angle + 1, TRACK, radius=70)
        start_color, end_color = (RED, AMBER) if low else (TEAL, LIME)
        end = 30 + round(value * 3)
        for angle in range(30, end):
            self.arc(angle, angle + 1, mix(start_color, end_color, (angle - 30) / 300), radius=70)
        for a, color in [(30, TRACK), (330, TRACK)]:
            angle = math.radians(a)
            self.dot(round(85 - 65 * math.sin(angle)), round(124 + 65 * math.cos(angle)), 5, color)
        if value:
            for a, color in [(30, start_color), (end, mix(start_color, end_color, value / 100))]:
                angle = math.radians(a)
                self.dot(round(85 - 65 * math.sin(angle)), round(124 + 65 * math.cos(angle)), 5, color)
        self.center(caption, 85, 79)
        number = str(round(value))
        digit_width, unit_width = FONTS[24].width(number), FONTS[12].width('%')
        x = 85 - (digit_width + unit_width + 3) // 2
        self.text(number, x, 102, 24, WHITE)
        self.text('%', x + digit_width + 3, 118, 12, MUTED)
        self.center('remaining' if caption == 'QUOTA' else 'hit rate', 85, 151, 9, start_color)
        for i in range(3):
            self.dot(77 + i * 8, 189, 2 if i == 1 else 1, end_color if i == 1 else TRACK)

    def metric(self, x, y, width, height, title, value, accent, size=18):
        self.box(x, y, width, height, 12, CARD)
        self.text(title, x + 12, y + 9)
        self.dot(x + width - 13, y + 15, 3, accent)
        if FONTS[size].width(value) > width - 24:
            size = 18
        if FONTS[size].width(value) > width - 24:
            size = 12
        self.text(self.fit(value, width - 24, size), x + 12, y + 31, size, WHITE)

    def bar(self, x, y, width, height, fraction, color):
        self.box(x, y, width, height, height // 2, TRACK)
        if fraction > 0:
            self.box(x, y, max(1, round(width * fraction)), height, min(height // 2, round(width * fraction) // 2), color)

    def quota_window(self, x, caption, value, weekly=False):
        y = 114
        valid = value >= 0
        start = (RED if value <= 20 else BLUE if weekly else TEAL) if valid else MUTED
        finish = AMBER if value <= 20 else LIME
        bounds = ((x-66)*SCALE, (y-66)*SCALE, (x+66)*SCALE, (y+66)*SCALE)
        self.draw.arc(bounds, 120, 420, fill=TRACK, width=9*SCALE)
        end = 30 + round(max(0, value)*3)
        for a in range(30, end):
            self.draw.arc(bounds, a+90, a+91, fill=mix(start, finish, (a-30)/300), width=9*SCALE)
        for a, color in [(30, TRACK), (330, TRACK)] + ([(30, start), (end, mix(start, finish, value/100))] if valid and value else []):
            r = math.radians(a)
            self.dot(round(x-61.5*math.sin(r)), round(y+61.5*math.cos(r)), 4, color)
        self.center(caption, x, 75)
        number = str(round(value)) if valid else '--'
        size = 18 if value >= 99.5 else 24
        digits = FONTS[size].width(number)
        unit = FONTS[9].width('%')+2 if valid else 0
        left = x-(digits+unit)//2
        self.text(number, left, 107 if size == 18 else 99, size, WHITE)
        if valid:
            self.text('%', left+digits+2, 119)
        self.center(('6d19h' if weekly else '1h23m') if valid else '--', x, 148, color=start)
        reset_label = ('10/31 11:55' if weekly else '16:55') if valid else ('--/-- --:--' if weekly else '--:--')
        self.center(reset_label, x, 188, color=WHITE)
        clock_x = x-FONTS[9].width(reset_label)//2-10
        self.draw.ellipse(((clock_x-4)*SCALE,190*SCALE,(clock_x+4)*SCALE,198*SCALE), outline=MUTED, width=SCALE)
        self.draw.line((clock_x*SCALE,191*SCALE,clock_x*SCALE,194*SCALE,(clock_x+2)*SCALE,194*SCALE), fill=MUTED,width=SCALE)

    def body(self, quota=51, weekly=92):
        if self.page == 0:
            self.quota_window(80, '5H', quota)
            self.quota_window(240, 'WEEK', weekly, True)
        elif self.page == 1:
            self.text('Requests', 14, 48, 12, WHITE)
            self.right(self.fit('gpt-6.1-sol', 168), 306, 53)
            self.metric(14, 83, 176, 79, 'Success', '95.5%', TEAL, 24)
            self.metric(199, 83, 109, 79, 'Errors', '8', RED, 24)
            self.bar(14, 169, 294, 6, .955, TEAL)
            self.text('6.8s first token', 14, 185)
            self.right('200 / 9.2s', 306, 185, 9, WHITE)
        elif self.page == 2:
            self.text('30 days', 14, 48, 12, WHITE)
            self.right(self.fit('deepseek-v4.1-flash', 175), 306, 53)
            self.metric(14, 83, 143, 79, 'Sessions', '118', BLUE, 24)
            self.metric(166, 83, 142, 79, 'Calls', '5.6K', LIME, 24)
            self.text('IN 28.5M', 14, 174, 9, WHITE)
            self.right('OUT 4.25M', 306, 174, 9, WHITE)
            self.bar(14, 196, 143, 5, .87, BLUE)
            self.bar(166, 196, 142, 5, .13, LIME)
        else:
            self.ring(97, 'CACHE')
            self.metric(173, 52, 135, 68, 'Reasoning', '1.33M', BLUE)
            self.metric(173, 129, 135, 68, 'Est. cost', '$35.37', LIME)
        return self

    def image(self):
        return self.im.resize((320, 240), Image.Resampling.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pages = [Preview(n).body().image() for n in range(4)]
    contact = Image.new('RGB', (680, 520), '#050b12')
    for n, page in enumerate(pages):
        contact.paste(page, (12 + n % 2 * 336, 12 + n // 2 * 256))
        page.save(OUT / f'page_{n + 1}.png')
    contact.resize((1360, 1040), Image.Resampling.NEAREST).save(OUT / 'overview.png')
    limits = Image.new('RGB', (680, 520), '#050b12')
    for n, quota in enumerate((0, 1, -1, 100)):
        limits.paste(Preview().body(quota, quota).image(), (12 + n % 2 * 336, 12 + n // 2 * 256))
    limits.resize((1360, 1040), Image.Resampling.NEAREST).save(OUT / 'quota_limits.png')
    waiting = Preview(status='OFFLINE')
    waiting.draw.rectangle((0, 43 * SCALE, 320 * SCALE, 240 * SCALE), fill=BG)
    for i in range(12):
        a = i * math.pi / 6
        waiting.dot(round(160 + math.sin(a) * 30), round(96 - math.cos(a) * 30), 3, mix(TRACK, TEAL, i / 11))
    waiting.center('Ready when you are', 160, 143, 12, WHITE)
    waiting.center('Pair Bluetooth, then start app', 160, 179)
    pairing = Preview(status='LINKING')
    pairing.draw.rectangle((0, 43 * SCALE, 320 * SCALE, 240 * SCALE), fill=BG)
    pairing.center('Pair your display', 160, 52, 12, WHITE)
    pairing.box(27, 93, 266, 69, 16, CARD)
    pairing.center('123 456', 160, 105, 24, TEAL)
    pairing.center('Enter code in Windows Bluetooth', 160, 180)
    full = Preview(1).body()
    full.box(14, 83, 176, 79, 12, CARD)
    full.metric(14, 83, 176, 79, 'Success', '100%', TEAL, 24)
    extremes = Preview(2).body()
    extremes.draw.rectangle((120 * SCALE, 44 * SCALE, 319 * SCALE, 77 * SCALE), fill=BG)
    extremes.right(extremes.fit('model-with-a-very-long-name', 175), 306, 53)
    states = Image.new('RGB', (680, 520), '#050b12')
    for n, scene in enumerate((waiting, pairing, full, extremes)):
        states.paste(scene.image(), (12 + n % 2 * 336, 12 + n // 2 * 256))
    states.resize((1360, 1040), Image.Resampling.NEAREST).save(OUT / 'states.png')
    frames = []
    for n in range(30):
        t = min(1, n / 24)
        frames.append(Preview().body(51 * (1 - (1 - t) ** 3), 92 * (1 - (1 - t) ** 3)).image().resize((640, 480), Image.Resampling.NEAREST))
    frames[0].save(OUT / 'quota_animation.gif', save_all=True, append_images=frames[1:],
                   duration=[40] * 29 + [1400], loop=0)
    print(OUT / 'overview.png')


if __name__ == '__main__':
    main()
