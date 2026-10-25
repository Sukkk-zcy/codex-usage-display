#include "smooth_text.h"
#include "fonts/dashboard_fonts.h"

const DashboardFont kDashboardFont9{kGlyphs9, kPixels9, kCapHeight9};
const DashboardFont kDashboardFont12{kGlyphs12, kPixels12, kCapHeight12};
const DashboardFont kDashboardFont18{kGlyphs18, kPixels18, kCapHeight18};
const DashboardFont kDashboardFont24{kGlyphs24, kPixels24, kCapHeight24};

namespace {
uint8_t asciiGlyph(uint8_t code) {
  return code >= 32 && code <= 126 ? code - 32 : '?' - 32;
}

uint8_t coverage(const uint8_t* pixels, uint32_t index) {
  const uint8_t packed = pgm_read_byte(pixels + index / 2);
  return index & 1 ? packed & 15 : packed >> 4;
}

uint16_t mixCoverage(uint16_t foreground, uint16_t background, uint8_t alpha) {
  const uint16_t inverse = 15 - alpha;
  const uint16_t r = (((foreground >> 11) & 31) * alpha + ((background >> 11) & 31) * inverse + 7) / 15;
  const uint16_t g = (((foreground >> 5) & 63) * alpha + ((background >> 5) & 63) * inverse + 7) / 15;
  const uint16_t b = ((foreground & 31) * alpha + (background & 31) * inverse + 7) / 15;
  return (r << 11) | (g << 5) | b;
}
} // namespace

int dashboardTextWidth(const String& text, const DashboardFont& font) {
  int advance = 0, right = 0;
  for (unsigned int i = 0; i < text.length(); ++i) {
    const DashboardGlyph& glyph = font.glyphs[asciiGlyph(static_cast<uint8_t>(text[i]))];
    right = max(right, advance + glyph.dx + glyph.width);
    advance += glyph.advance;
  }
  return max(right, advance);
}

void drawDashboardText(TFT_eSprite& canvas, const String& text, int x, int y,
                       const DashboardFont& font, uint16_t foreground, uint16_t background) {
  uint16_t palette[16];
  for (uint8_t a = 0; a < 16; ++a) palette[a] = mixCoverage(foreground, background, a);
  for (unsigned int i = 0; i < text.length(); ++i) {
    const DashboardGlyph& glyph = font.glyphs[asciiGlyph(static_cast<uint8_t>(text[i]))];
    const uint8_t* pixels = font.pixels + glyph.offset;
    for (uint8_t row = 0; row < glyph.height; ++row) {
      uint8_t col = 0;
      while (col < glyph.width) {
        const uint8_t alpha = coverage(pixels, row * glyph.width + col);
        const uint8_t start = col++;
        while (col < glyph.width && coverage(pixels, row * glyph.width + col) == alpha) ++col;
        if (alpha) canvas.drawFastHLine(x + glyph.dx + start, y + glyph.dy + row, col - start, palette[alpha]);
      }
    }
    x += glyph.advance;
  }
}
