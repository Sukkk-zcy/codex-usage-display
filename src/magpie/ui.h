#pragma once

#include <TFT_eSPI.h>
#include "app_state.h"

struct DashboardView {
  const AppState* state;
  uint32_t now = 0;
  uint32_t received_at = 0;
  uint32_t pairing_code = 0;
  uint8_t page = 0;
  bool connected = false;
  bool synchronized = false;
  bool has_snapshot = false;
  bool pairing = false;
  float quota = 0;
  float weekly_quota = 0;
  float cache_hit = 0;
  float entrance = 1;
  int8_t direction = 1;
  const char* notice = nullptr;
};

constexpr uint16_t kDashboardBackground = 0x0862;
void drawDashboard(TFT_eSprite& canvas, const DashboardView& view);
