#pragma once

#include <TFT_eSPI.h>

// Packed 4-bit coverage masks live in Flash, not the framebuffer or heap.
struct DashboardGlyph {
  uint32_t offset;
  uint8_t width, height, advance;
  int8_t dx, dy;
};

struct DashboardFont {
  const DashboardGlyph* glyphs;
  const uint8_t* pixels;
  uint8_t cap_height;
};

extern const DashboardFont kDashboardFont9;
extern const DashboardFont kDashboardFont12;
extern const DashboardFont kDashboardFont18;
extern const DashboardFont kDashboardFont24;

int dashboardTextWidth(const String& text, const DashboardFont& font);
void drawDashboardText(TFT_eSprite& canvas, const String& text, int x, int y,
                       const DashboardFont& font, uint16_t foreground, uint16_t background);
