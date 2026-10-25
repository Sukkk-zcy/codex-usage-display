#include <Arduino.h>
#include <OneButton.h>
#include <TFT_eSPI.h>
#include "board_config.h"
#include "ble_bridge.h"
#include "ui.h"

namespace {
TFT_eSPI tft;
TFT_eSprite frame(&tft);
OneButton left(kButtonLeft, true), middle(kButtonMiddle, true), right(kButtonRight, true);
AppState state;
uint8_t page = 0;
uint32_t receivedAt = 0, lastPaintAt = 0, noticeUntil = 0;
uint32_t quotaStartedAt = 0, pageEnteredAt = 0;
bool hasSnapshot = false, dirty = true, awake = true, pairing = false;
uint32_t pairingCode = 0;
float quotaFrom = 0, quotaTarget = 0, cacheFrom = 0, cacheTarget = 0;
float weeklyFrom = 0, weeklyTarget = 0;
int8_t slideDirection = 1;
String notice;
void render();

float easeOut(float t) {
  t = constrain(t, 0.0f, 1.0f);
  const float remaining = 1 - t;
  return 1 - remaining * remaining * remaining;
}
float animatedValue(float from, float to, uint32_t now) {
  return from + (to - from) * easeOut((now - quotaStartedAt) / 950.0f);
}
void showNotice(const String& message) {
  notice = message;
  noticeUntil = millis() + 3000;
  dirty = true;
}
bool wake() {
  if (awake) return false;
  awake = true;
  pageEnteredAt = millis();
  analogWrite(kBacklight, kBrightness);
  dirty = true;
  return true;
}
void changePage(int direction) {
  if (!wake()) {
    page = (page + 4 + direction) % 4;
    slideDirection = direction;
    pageEnteredAt = millis();
  }
  dirty = true;
}
void previous() { changePage(-1); }
void next() { changePage(1); }
void toggleScreen() {
  awake = !awake;
  analogWrite(kBacklight, awake ? kBrightness : 0);
  pageEnteredAt = millis();
  dirty = true;
}
void refresh() {
  if (wake()) return;
  showNotice(bleSendAction("refresh") ? "Refreshing..." : "Start the companion on your PC");
}
void focus() {
  if (wake()) return;
  showNotice(bleSendAction("focus_magpie") ? "Opening Magpie..." : "Start the companion on your PC");
}
void clearPairing() {
  wake();
  if (!bleClearBonds()) { showNotice("Could not clear pairing"); return; }
  showNotice("Pairing cleared. Restarting...");
  render();
  Serial.println("[ble] pairing cleared; restarting");
  delay(1200); // Bond removal is asynchronous in ESP-IDF.
  ESP.restart();
}
void render() {
  const uint32_t now = millis();
  DashboardView view;
  view.state = &state;
  view.now = now;
  view.received_at = receivedAt;
  view.pairing_code = pairingCode;
  view.page = page;
  view.connected = bleConnected();
  view.synchronized = bleSynchronized();
  view.has_snapshot = hasSnapshot;
  view.pairing = pairing;
  view.quota = animatedValue(quotaFrom, quotaTarget, now);
  view.weekly_quota = animatedValue(weeklyFrom, weeklyTarget, now);
  view.cache_hit = animatedValue(cacheFrom, cacheTarget, now);
  view.entrance = easeOut((now - pageEnteredAt) / 280.0f);
  view.direction = slideDirection;
  view.notice = noticeUntil && static_cast<int32_t>(noticeUntil - now) > 0 ? notice.c_str() : nullptr;
  drawDashboard(frame, view);
}
} // namespace

void setup() {
  Serial.begin(115200);
  pinMode(kSensorPower, OUTPUT);
  digitalWrite(kSensorPower, LOW);
  pinMode(kBuzzer, OUTPUT);
  digitalWrite(kBuzzer, LOW);
  tft.init();
  tft.setRotation(1);
  tft.fillScreen(kDashboardBackground);
  analogWrite(kBacklight, kBrightness);
  // Reuse the same 76,800-byte 8-bit framebuffer; no PSRAM or second buffer.
  frame.setColorDepth(8);
  if (!frame.createSprite(320, 240)) {
    tft.setTextColor(TFT_RED, kDashboardBackground);
    tft.drawString("Display buffer allocation failed", 8, 40, 2);
    while (true) delay(1000);
  }
  render();
  if (!bleBegin()) {
    tft.setTextColor(TFT_RED, kDashboardBackground);
    tft.drawString("BLE initialization failed", 8, 70, 2);
    while (true) delay(1000);
  }
  left.attachClick(previous);
  right.attachClick(next);
  middle.attachClick(refresh);
  middle.setPressMs(1000);
  middle.attachLongPressStart(focus);
  left.setPressMs(3000);
  left.attachLongPressStart(clearPairing);
  right.setPressMs(1000);
  right.attachLongPressStart(toggleScreen);
  Serial.printf("[system] ESP32 dashboard ready; free heap=%u\n", ESP.getFreeHeap());
}

void loop() {
  left.tick(); middle.tick(); right.tick();
  bleMaintainConnection();
  const uint32_t now = millis();
  AppState updated;
  if (bleTakeState(updated)) {
    quotaFrom = animatedValue(quotaFrom, quotaTarget, now);
    weeklyFrom = animatedValue(weeklyFrom, weeklyTarget, now);
    cacheFrom = animatedValue(cacheFrom, cacheTarget, now);
    quotaTarget = max(0, static_cast<int>(updated.short_remaining_percent));
    weeklyTarget = max(0, static_cast<int>(updated.weekly_remaining_percent));
    cacheTarget = updated.cache_hit_permille / 10.0f;
    quotaStartedAt = now;
    if (!hasSnapshot) pageEnteredAt = now;
    state = updated;
    receivedAt = now;
    hasSnapshot = true;
    pairing = false;
    dirty = true;
  }
  uint32_t code;
  if (bleTakePairingCode(code)) { pairingCode = code; pairing = true; wake(); dirty = true; }
  bool paired;
  if (bleTakePairingFinished(paired)) {
    pairing = false;
    showNotice(paired ? "Paired. Ready to connect" : "Pairing failed. Try again");
  }
  BleActionResult result;
  if (bleTakeActionResult(result)) showNotice(String(result.message) == "UPDATED" ? "Updated just now" : result.message);
  if (pairing && !bleConnected()) { pairing = false; dirty = true; }
  const bool animating = !hasSnapshot || pairing || now - quotaStartedAt < 1200 || now - pageEnteredAt < 300;
  if (now - quotaStartedAt >= 950) {
    quotaFrom = quotaTarget; weeklyFrom = weeklyTarget; cacheFrom = cacheTarget;
  }
  // Fast while transitioning; a gentle status pulse at idle. No blocking animation.
  const uint32_t interval = animating ? 40 : 120;
  if (awake && (dirty || now - lastPaintAt >= interval)) {
    render();
    dirty = false;
    lastPaintAt = millis();
  }
  delay(5);
}

