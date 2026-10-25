#pragma once

// Matches the legacy clock wiring and lib/TFT_eSPI/User_Setup.h.
// Independent of the legacy clock's weather images, fonts and sensors.
constexpr int kBacklight = 17;
constexpr int kButtonLeft = 25;
constexpr int kButtonMiddle = 26;
constexpr int kButtonRight = 27;
constexpr int kSensorPower = 12;
constexpr int kBuzzer = 13;
constexpr uint8_t kBrightness = 50;
constexpr uint32_t kStaleMs = 60000;
