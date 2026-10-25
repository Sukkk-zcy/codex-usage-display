#include "ui.h"
#include "board_config.h"
#include "smooth_text.h"
#include <math.h>

namespace {
constexpr uint16_t kBg = kDashboardBackground;
constexpr uint16_t kCard = 0x10C4, kTrack = 0x2166, kMuted = 0x94F4;
constexpr uint16_t kWhite = 0xEF9E, kTeal = 0x3F59, kLime = 0xCFCB;
constexpr uint16_t kAmber = 0xFD8B, kRed = 0xFA8C, kBlue = 0x6D9F;
constexpr float kPi = 3.14159265359f;

uint16_t blend(uint16_t a, uint16_t b, float t) {
  t = constrain(t, 0.0f, 1.0f);
  const int r = ((a >> 11) & 31) + (((b >> 11) & 31) - ((a >> 11) & 31)) * t;
  const int g = ((a >> 5) & 63) + (((b >> 5) & 63) - ((a >> 5) & 63)) * t;
  const int blue = (a & 31) + ((b & 31) - (a & 31)) * t;
  return (r << 11) | (g << 5) | blue;
}

class Painter {
 public:
  Painter(TFT_eSprite& canvas, const DashboardView& view) : c(canvas), v(view), s(*view.state) {}

  void draw() {
    c.resetViewport();
    c.fillSprite(kBg);
    header();
    // Animate only the content. The status and page controls stay anchored.
    c.setViewport(0, 43, 320, 161, false);
    c.setOrigin(lroundf((1.0f - v.entrance) * 22 * v.direction), 0);
    if (v.pairing) pairing();
    else if (!v.has_snapshot) waiting();
    else if (v.page == 0) overview();
    else if (v.page == 1) requests();
    else if (v.page == 2) sessions();
    else context();
    c.resetViewport();
    footer();
    c.setFreeFont(nullptr);
    c.pushSprite(0, 0);
  }

 private:
  TFT_eSprite& c;
  const DashboardView& v;
  const AppState& s;
  const DashboardFont* activeFont = &kDashboardFont9;

  void font(const DashboardFont* face) { activeFont = face; }
  int textWidth(const String& value) const { return dashboardTextWidth(value, *activeFont); }
  void label(const String& value, int x, int y, uint16_t color = kMuted,
             const DashboardFont* face = &kDashboardFont9, uint16_t bg = kBg) {
    font(face);
    drawDashboardText(c, value, x, y, *activeFont, color, bg);
  }
  String fit(String value, int width, const DashboardFont* face) {
    font(face);
    if (textWidth(value) <= width) return value;
    while (value.length() && textWidth(value + "..") > width) value.remove(value.length() - 1);
    return value + "..";
  }
  void center(const String& value, int x, int y, uint16_t color,
              const DashboardFont* face = &kDashboardFont9) {
    font(face);
    label(value, x - textWidth(value) / 2, y, color, face);
  }
  void right(const String& value, int x, int y, uint16_t color,
             const DashboardFont* face = &kDashboardFont9, uint16_t bg = kBg) {
    font(face);
    label(value, x - textWidth(value), y, color, face, bg);
  }
  bool fresh() const { return v.synchronized && v.has_snapshot && v.now - v.received_at < kStaleMs; }

  void header() {
    // Small geometric brand mark, drawn natively rather than a bitmap asset.
    c.fillSmoothCircle(17, 22, 5, kTeal, kBg);
    c.fillSmoothCircle(27, 16, 3, kLime, kBg);
    c.fillSmoothCircle(28, 27, 2, kTeal, kBg);
    label("magpie", 40, 10, kWhite, &kDashboardFont12);
    const bool live = fresh();
    const char* status = live ? "LIVE" : !v.connected ? "OFFLINE" : !v.synchronized ? "LINKING" : "STALE";
    const uint16_t color = live ? kTeal : kAmber;
    font(&kDashboardFont9);
    const int pillWidth = textWidth(status) + 30;
    const int pillLeft = 308 - pillWidth;
    c.fillSmoothRoundRect(pillLeft, 10, pillWidth, 25, 12, kCard, kBg);
    const float pulse = 0.5f + 0.5f * sinf(v.now * 0.004f);
    c.fillSmoothCircle(pillLeft + 12, 22, 5, blend(kCard, color, live ? 0.12f + pulse * 0.14f : 0.16f), kCard);
    c.fillSmoothCircle(pillLeft + 12, 22, 2, color, kCard);
    label(status, pillLeft + 23, 16, color, &kDashboardFont9, kCard);
  }

  void bar(int x, int y, int width, int height, float fraction, uint16_t color, uint16_t bg = kBg) {
    c.fillSmoothRoundRect(x, y, width, height, height / 2, kTrack, bg);
    const int filled = lroundf(constrain(fraction, 0.0f, 1.0f) * width);
    if (filled >= height) c.fillSmoothRoundRect(x, y, filled, height, height / 2, color, bg);
    else if (filled > 0) c.fillRect(x, y + 1, filled, height - 2, color);
  }

  void ring(float value, const char* caption, bool quota) {
    constexpr int x = 85, y = 124, outer = 70, inner = 60;
    value = constrain(value, 0.0f, 100.0f);
    const bool low = quota && s.remaining_percent <= 20;
    const uint16_t startColor = !fresh() ? kMuted : low ? kRed : kTeal;
    const uint16_t endColor = !fresh() ? kMuted : low ? kAmber : kLime;
    c.drawSmoothArc(x, y, outer, inner, 30, 330, kTrack, kBg, true);
    const int end = 30 + lroundf(value * 3);
    if (end > 30) {
      for (int angle = 30; angle < end; angle += 6) {
        c.drawArc(x, y, outer, inner, angle, min(angle + 6, end),
                  blend(startColor, endColor, (angle - 30) / 300.0f), kBg);
      }
      const float start = 30 * kPi / 180;
      const float finish = end * kPi / 180;
      c.fillSmoothCircle(lroundf(x - 65 * sinf(start)), lroundf(y + 65 * cosf(start)), 5, startColor, kBg);
      c.fillSmoothCircle(lroundf(x - 65 * sinf(finish)), lroundf(y + 65 * cosf(finish)), 5,
                         blend(startColor, endColor, value / 100), kBg);
    }
    center(caption, x, 79, kMuted);
    const String number = String(static_cast<int>(lroundf(value)));
    font(&kDashboardFont24);
    const int digitsWidth = textWidth(number);
    font(&kDashboardFont12);
    const int unitWidth = textWidth("%");
    const int start = x - (digitsWidth + unitWidth + 3) / 2;
    label(number, start, 102, kWhite, &kDashboardFont24);
    label("%", start + digitsWidth + 3, 118, kMuted, &kDashboardFont12);
    center(quota ? "remaining" : "hit rate", x, 151, fresh() ? startColor : kMuted);
    // A small marker in the open part of the ring, rather than another label.
    for (int i = 0; i < 3; ++i) c.fillCircle(77 + i * 8, 189, i == 1 ? 2 : 1, i == 1 ? endColor : kTrack);
  }

  void metric(int x, int y, int width, int height, const char* title, const String& value,
              uint16_t accent, const DashboardFont* preferred = &kDashboardFont18) {
    c.fillSmoothRoundRect(x, y, width, height, 12, kCard, kBg);
    label(title, x + 12, y + 9, kMuted, &kDashboardFont9, kCard);
    c.fillSmoothCircle(x + width - 13, y + 15, 3, accent, kCard);
    const DashboardFont* face = preferred;
    font(face);
    if (textWidth(value) > width - 24) face = &kDashboardFont18;
    font(face);
    if (textWidth(value) > width - 24) face = &kDashboardFont12;
    label(fit(value, width - 24, face), x + 12, y + 31, kWhite, face, kCard);
  }

  void overview() {
    quotaWindow(80, "5H", v.quota, s.short_remaining_percent, s.short_reset_at, false);
    quotaWindow(240, "WEEK", v.weekly_quota, s.weekly_remaining_percent, s.weekly_reset_at, true);
  }

  void quotaWindow(int x, const char* caption, float animated, int actual, uint32_t reset, bool weekly) {
    constexpr int y = 114, outer = 66, inner = 57;
    const bool valid = actual >= 0;
    const bool low = valid && actual <= 20;
    const uint16_t accent = !fresh() || !valid ? kMuted : low ? kRed : weekly ? kBlue : kTeal;
    const uint16_t finishColor = !fresh() || !valid ? kMuted : low ? kAmber : kLime;
    const float value = valid ? constrain(animated, 0.0f, 100.0f) : 0;
    c.drawSmoothArc(x, y, outer, inner, 30, 330, kTrack, kBg, true);
    const int end = 30 + lroundf(value * 3);
    if (valid && end > 30) {
      for (int a = 30; a < end; a += 6)
        c.drawArc(x, y, outer, inner, a, min(a + 6, end), blend(accent, finishColor, (a - 30) / 300.0f), kBg);
      for (int a : {30, end}) {
        const float rad = a * kPi / 180;
        c.fillSmoothCircle(lroundf(x - 61.5f * sinf(rad)), lroundf(y + 61.5f * cosf(rad)), 4.5f,
            a == 30 ? accent : blend(accent, finishColor, value / 100), kBg);
      }
    }
    center(caption, x, 75, kMuted);
    const String number = valid ? String(static_cast<int>(lroundf(value))) : "--";
    const DashboardFont* face = value >= 99.5f ? &kDashboardFont18 : &kDashboardFont24;
    font(face);
    const int digits = textWidth(number);
    font(&kDashboardFont9);
    const int unit = valid ? textWidth("%") + 2 : 0;
    label(number, x - (digits + unit) / 2, face == &kDashboardFont24 ? 99 : 107, kWhite, face);
    if (valid) label("%", x - (digits + unit) / 2 + digits + 2, 119, kMuted);
    const uint64_t now = s.unix_time + (v.now - v.received_at) / 1000;
    String countdown = "--";
    if (reset) {
      if (now >= reset) countdown = "DUE";
      else if (reset - now < 60) countdown = String(static_cast<unsigned long>(reset - now)) + "s";
      else { countdown = formatCountdown(reset - now); countdown.replace(" ", ""); }
    }
    center(countdown, x, 148, accent);
    const String resetLabel = formatResetTime(s, reset, weekly);
    center(resetLabel, x, 188, kWhite);
    font(&kDashboardFont9);
    const int clockX = x - textWidth(resetLabel) / 2 - 10;
    c.drawSmoothArc(clockX, 194, 4, 3, 0, 360, kMuted, kBg);
    c.drawLine(clockX, 194, clockX, 191, kMuted);
    c.drawLine(clockX, 194, clockX + 2, 194, kMuted);
  }

  void requests() {
    label("Requests", 14, 48, kWhite, &kDashboardFont12);
    right(fit(s.latest_model, 168, &kDashboardFont9), 306, 53, kMuted);
    metric(14, 83, 176, 79, "Success", s.success_permille == 1000 ? "100%" : String(s.success_permille / 10.0, 1) + "%", kTeal, &kDashboardFont24);
    metric(199, 83, 109, 79, "Errors", formatCompactTokens(s.errors_today), s.errors_today ? kRed : kTeal, &kDashboardFont24);
    bar(14, 169, 294, 6, s.success_permille / 1000.0f, kTeal);
    label(String(s.average_ttft_ms / 1000.0, 1) + "s first token", 14, 185, kMuted);
    right(String(s.latest_status) + " / " + String(s.latest_latency_ms / 1000.0, 1) + "s", 306, 185,
          s.latest_failed ? kRed : kWhite);
  }

  void sessions() {
    label("30 days", 14, 48, kWhite, &kDashboardFont12);
    right(fit(s.top_model, 175, &kDashboardFont9), 306, 53, kMuted);
    metric(14, 83, 143, 79, "Sessions", formatCompactTokens(s.session_count), kBlue, &kDashboardFont24);
    metric(166, 83, 142, 79, "Calls", formatCompactTokens(s.total_calls), kLime, &kDashboardFont24);
    label("IN " + formatCompactTokens(s.total_input), 14, 174, kWhite);
    right("OUT " + formatCompactTokens(s.total_output), 306, 174, kWhite);
    const double total = static_cast<double>(s.total_input) + s.total_output;
    bar(14, 196, 143, 5, total ? s.total_input / total : 0, kBlue);
    bar(166, 196, 142, 5, total ? s.total_output / total : 0, kLime);
  }

  void context() {
    ring(v.cache_hit, "CACHE", false);
    metric(173, 52, 135, 68, "Reasoning", formatCompactTokens(s.total_reasoning), kBlue);
    metric(173, 129, 135, 68, "Est. cost", "$" + String(s.total_cost_micros / 1000000.0, 2), kLime);
  }

  void orbit(int x, int y, int radius) {
    const int phase = (v.now / 100) % 12;
    for (int i = 0; i < 12; ++i) {
      const float angle = i * kPi / 6;
      c.fillSmoothCircle(lroundf(x + sinf(angle) * radius), lroundf(y - cosf(angle) * radius), 3,
                         blend(kTrack, kTeal, ((i - phase + 12) % 12) / 11.0f), kBg);
    }
  }

  void pairing() {
    center("Pair your display", 160, 52, kWhite, &kDashboardFont12);
    char code[12];
    snprintf(code, sizeof(code), "%03lu %03lu", static_cast<unsigned long>(v.pairing_code / 1000),
             static_cast<unsigned long>(v.pairing_code % 1000));
    c.fillSmoothRoundRect(27, 93, 266, 69, 16, kCard, kBg);
    font(&kDashboardFont24);
    label(code, 160 - textWidth(code) / 2, 105, kTeal, &kDashboardFont24, kCard);
    center("Enter code in Windows Bluetooth", 160, 180, kMuted);
  }

  void waiting() {
    orbit(160, 96, 30);
    center("Ready when you are", 160, 143, kWhite, &kDashboardFont12);
    center(v.connected ? "Waiting for usage data" : "Pair Bluetooth, then start app", 160, 179, kMuted);
  }

  void footer() {
    if (v.notice && *v.notice) {
      c.fillSmoothRoundRect(12, 207, 296, 28, 13, kTrack, kBg);
      c.fillSmoothCircle(25, 221, 3, kTeal, kTrack);
      label(fit(v.notice, 265, &kDashboardFont9), 36, 213, kWhite, &kDashboardFont9, kTrack);
      return;
    }
    const String clock = formatDateTime(s, v.has_snapshot ? (v.now - v.received_at) / 1000 : 0);
    label(clock.substring(6), 14, 213, kWhite, &kDashboardFont12);
    if (v.has_snapshot && !v.pairing) {
      for (int i = 0; i < 4; ++i) {
        if (i == v.page) c.fillSmoothRoundRect(255 + i * 14, 221, 14, 5, 2, kTeal, kBg);
        else c.fillSmoothCircle(259 + i * 14, 223, 2, kTrack, kBg);
      }
    }
    if (fresh() && v.now - v.received_at < 1200) {
      const int a = (v.now % 800) * 360 / 800;
      c.drawSmoothArc(91, 224, 5, 3, a, (a + 235) % 360, kTeal, kBg, true);
    }
  }
};
} // namespace

void drawDashboard(TFT_eSprite& canvas, const DashboardView& view) {
  Painter(canvas, view).draw();
}
