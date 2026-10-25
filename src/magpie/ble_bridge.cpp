#include "ble_bridge.h"

#include <ArduinoJson.h>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLESecurity.h>

#if defined(CONFIG_NIMBLE_ENABLED)
#include <host/ble_store.h>
#endif

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

namespace {

constexpr char kDeviceName[] = "Magpie Display";
constexpr char kServiceUuid[] = "7d8b6c20-8f6d-4b44-a0f8-1b6570c0de01";
constexpr char kStatusUuid[] = "7d8b6c20-8f6d-4b44-a0f8-1b6570c0de02";
constexpr char kCommandUuid[] = "7d8b6c20-8f6d-4b44-a0f8-1b6570c0de03";
constexpr char kResultUuid[] = "7d8b6c20-8f6d-4b44-a0f8-1b6570c0de04";
constexpr char kDeviceInfoUuid[] = "7d8b6c20-8f6d-4b44-a0f8-1b6570c0de05";
constexpr uint8_t kProtocolVersion = 4;
constexpr uint32_t kStatusWatchdogMs = 45 * 1000;

BLEServer* server = nullptr;
BLECharacteristic* command_characteristic = nullptr;
QueueHandle_t state_queue = nullptr;
QueueHandle_t result_queue = nullptr;
QueueHandle_t pairing_code_queue = nullptr;
QueueHandle_t pairing_finished_queue = nullptr;
volatile bool connected = false;
volatile bool status_received_on_connection = false;
volatile uint32_t last_status_at_ms = 0;
volatile uint32_t connected_at_ms = 0;
uint32_t next_request_id = 1;
uint32_t command_session_id = 0;
uint32_t last_sequence = 0;
bool has_bonded_device = false;
bool pairing_code_announced = false;

class ServerCallbacks final : public BLEServerCallbacks {
 public:
  void onConnect(BLEServer*) override {
    connected = true;
    status_received_on_connection = false;
    connected_at_ms = millis();
    xQueueReset(state_queue);
    last_sequence = 0;
    Serial.println("[ble] connected");
  }

  void onDisconnect(BLEServer* current_server) override {
    connected = false;
    status_received_on_connection = false;
    Serial.println("[ble] disconnected");
    current_server->startAdvertising();
  }
};

class StatusCallbacks final : public BLECharacteristicCallbacks {
 public:
  void onWrite(BLECharacteristic* characteristic) override {
    const std::string value = characteristic->getValue();
    if (value.empty() || value.length() > 250) {
      Serial.println("[ble] rejected invalid status length");
      return;
    }

    JsonDocument document;
    const DeserializationError error =
        deserializeJson(document, value.c_str(), value.length());
    if (error || !document.is<JsonObject>() || document["v"].as<uint8_t>() != kProtocolVersion ||
        !document["t"].is<uint64_t>() || document["t"].as<uint64_t>() == 0 ||
        !document["s"].is<uint32_t>()) {
      Serial.println("[ble] rejected invalid status JSON");
      return;
    }

    const uint32_t sequence = document["s"] | 0UL;
    if (sequence == 0 || (last_sequence != 0 && sequence < last_sequence)) {
      Serial.println("[ble] rejected stale status");
      return;
    }

    AppState state;
    state.unix_time = document["t"] | 0ULL;
    state.utc_offset_minutes = document["o"] | 0;
    state.remaining_percent =
        min<uint8_t>(document["r"] | 0, static_cast<uint8_t>(100));
    state.limit_window_minutes = document["u"] | 0UL;
    // q is the dual-window extension; old scalar countdown is no longer used.
    state.tokens_today = document["d"] | 0ULL;
    state.tokens_7d = document["w"] | 0ULL;
    state.calls_today = document["f"] | 0UL;
    state.errors_today = document["z"] | 0UL;
    state.success_permille =
        min<uint16_t>(document["y"] | 0, static_cast<uint16_t>(1000));
    state.average_ttft_ms = document["l"] | 0UL;
    strlcpy(state.latest_model, document["m"] | "-",
            sizeof(state.latest_model));
    state.latest_status = document["h"] | 0;
    state.latest_latency_ms = document["n"] | 0UL;
    state.latest_failed = (document["b"] | 0) == 1;
    JsonArray extended = document["x"].as<JsonArray>();
    state.session_count = extended[0] | 0;
    state.total_calls = extended[1] | 0UL;
    state.total_input = extended[2] | 0ULL;
    state.total_output = extended[3] | 0ULL;
    state.total_cache_read = extended[4] | 0ULL;
    state.total_reasoning = extended[5] | 0ULL;
    state.total_cost_micros = extended[6] | 0ULL;
    state.cache_hit_permille =
        min<uint16_t>(extended[7] | 0, static_cast<uint16_t>(1000));
    strlcpy(state.top_model, extended[8] | "-", sizeof(state.top_model));
    state.top_model_calls = extended[9] | 0UL;
    if (document["q"].is<JsonArray>()) {
      JsonArray windows = document["q"].as<JsonArray>();
      if (windows.size() != 4 || !windows[0].is<int>() || !windows[2].is<int>() ||
          !windows[1].is<uint32_t>() || !windows[3].is<uint32_t>() ||
          windows[0].as<int>() < -1 || windows[0].as<int>() > 100 ||
          windows[2].as<int>() < -1 || windows[2].as<int>() > 100) {
        Serial.println("[ble] rejected invalid quota windows");
        return;
      }
      state.short_remaining_percent = windows[0].as<int>();
      state.short_reset_at = windows[1].as<uint32_t>();
      state.weekly_remaining_percent = windows[2].as<int>();
      state.weekly_reset_at = windows[3].as<uint32_t>();
    } else if (document.containsKey("q") && !document["q"].is<uint32_t>()) {
      Serial.println("[ble] rejected invalid quota extension");
      return;
    }
    state.connection = ConnectionState::kLinked;
    state.time_valid = state.unix_time > 0;
    state.data_valid = true;

    last_sequence = sequence;
    last_status_at_ms = millis();
    status_received_on_connection = true;
    xQueueOverwrite(state_queue, &state);
    Serial.printf("[ble] status seq=%lu\n",
                  static_cast<unsigned long>(sequence));
  }
};

class ResultCallbacks final : public BLECharacteristicCallbacks {
 public:
  void onWrite(BLECharacteristic* characteristic) override {
    const std::string value = characteristic->getValue();
    if (value.empty() || value.size() > 256) return;
    JsonDocument document;
    if (deserializeJson(document, value.c_str(), value.length()) ||
        document["v"].as<uint8_t>() != kProtocolVersion) {
      return;
    }

    BleActionResult result{};
    const bool ok = (document["ok"] | 0) == 1;
    const char* message = document["m"] | (ok ? "DONE" : "FAILED");
    strlcpy(result.message, message, sizeof(result.message));
    xQueueOverwrite(result_queue, &result);
  }
};

class SecurityCallbacks final : public BLESecurityCallbacks {
 public:
  uint32_t onPassKeyRequest() override { return 0; }
  bool onConfirmPIN(uint32_t) override { return false; }
  void onPassKeyNotify(uint32_t passkey) override {
    pairing_code_announced = true;
    xQueueOverwrite(pairing_code_queue, &passkey);
    Serial.printf("[ble] pairing passkey %06lu\n",
                  static_cast<unsigned long>(passkey));
  }

  bool onSecurityRequest() override {
    return true;
  }

#if defined(CONFIG_BLUEDROID_ENABLED)
  void onAuthenticationComplete(esp_ble_auth_cmpl_t result) override {
    const bool success = result.success;
    if (success) {
      has_bonded_device = true;
    }
    if (pairing_code_announced) {
      xQueueOverwrite(pairing_finished_queue, &success);
      pairing_code_announced = false;
    }
    Serial.printf("[ble] pairing %s\n", success ? "complete" : "failed");
  }
#endif
};

}  // namespace

bool bleBegin() {
  state_queue = xQueueCreate(1, sizeof(AppState));
  result_queue = xQueueCreate(1, sizeof(BleActionResult));
  pairing_code_queue = xQueueCreate(1, sizeof(uint32_t));
  pairing_finished_queue = xQueueCreate(1, sizeof(bool));
  if (state_queue == nullptr || result_queue == nullptr ||
      pairing_code_queue == nullptr || pairing_finished_queue == nullptr) {
    Serial.println("[ble] failed to allocate queues");
    return false;
  }

  BLEDevice::init(kDeviceName);
#if defined(CONFIG_BLUEDROID_ENABLED)
  has_bonded_device = esp_ble_get_bond_device_num() > 0;
#endif
  command_session_id = esp_random();
  if (command_session_id == 0) {
    command_session_id = 1;
  }
  BLEDevice::setMTU(256);
  BLEDevice::setSecurityCallbacks(new SecurityCallbacks());

  auto* security = new BLESecurity();
  BLEDevice::setEncryptionLevel(ESP_BLE_SEC_ENCRYPT_MITM);
  security->setAuthenticationMode(ESP_LE_AUTH_REQ_SC_MITM_BOND);
  security->setCapability(ESP_IO_CAP_OUT);
  security->setInitEncryptionKey(ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK);
  security->setRespEncryptionKey(ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK);

  server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  BLEService* service = server->createService(kServiceUuid);
  BLECharacteristic* status = service->createCharacteristic(
      kStatusUuid, BLECharacteristic::PROPERTY_WRITE);
  status->setAccessPermissions(ESP_GATT_PERM_WRITE_ENCRYPTED);
  status->setCallbacks(new StatusCallbacks());

  command_characteristic = service->createCharacteristic(
      kCommandUuid,
      BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  command_characteristic->setAccessPermissions(ESP_GATT_PERM_READ_ENCRYPTED);
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
  auto* command_cccd = new BLE2902();
#pragma GCC diagnostic pop
  command_cccd->setAccessPermissions(ESP_GATT_PERM_READ |
                                     ESP_GATT_PERM_WRITE_ENCRYPTED);
  command_characteristic->addDescriptor(command_cccd);

  BLECharacteristic* result = service->createCharacteristic(
      kResultUuid, BLECharacteristic::PROPERTY_WRITE);
  result->setAccessPermissions(ESP_GATT_PERM_WRITE_ENCRYPTED);
  result->setCallbacks(new ResultCallbacks());

  BLECharacteristic* device_info = service->createCharacteristic(
      kDeviceInfoUuid, BLECharacteristic::PROPERTY_READ);
    device_info->setValue("{\"v\":4,\"fw\":\"esp32-st7789-1.1\",\"screen\":\"320x240\",\"quotas\":2}");

  service->start();
  BLEAdvertising* advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(kServiceUuid);
  advertising->setScanResponse(true);
  BLEDevice::startAdvertising();
  Serial.println("[ble] advertising as Magpie Display");
  return true;
}

bool bleConnected() {
  return connected;
}

bool bleSynchronized() { return connected && status_received_on_connection; }

void bleMaintainConnection() {
  if (!connected || server == nullptr ||
      (status_received_on_connection ? millis() - last_status_at_ms < kStatusWatchdogMs :
                                      millis() - connected_at_ms < 120000)) {
    return;
  }

  status_received_on_connection = false;
  Serial.println("[ble] status watchdog expired; disconnecting stale client");
  server->disconnect(server->getConnId());
}

void bleStartAdvertising() {
  if (!connected && server != nullptr) {
    server->startAdvertising();
  }
}

bool bleTakeState(AppState& state) {
  return state_queue != nullptr &&
         xQueueReceive(state_queue, &state, 0) == pdTRUE;
}

bool bleTakeActionResult(BleActionResult& result) {
  return result_queue != nullptr &&
         xQueueReceive(result_queue, &result, 0) == pdTRUE;
}

bool bleTakePairingCode(uint32_t& passkey) {
  return pairing_code_queue != nullptr &&
         xQueueReceive(pairing_code_queue, &passkey, 0) == pdTRUE;
}

bool bleTakePairingFinished(bool& success) {
  return pairing_finished_queue != nullptr &&
         xQueueReceive(pairing_finished_queue, &success, 0) == pdTRUE;
}

bool bleSendAction(const char* action) {
  if (!connected || command_characteristic == nullptr) {
    return false;
  }

  char message[96];
  const uint32_t request_id = next_request_id++;
  snprintf(message, sizeof(message),
           "{\"v\":%u,\"sid\":%lu,\"id\":%lu,\"a\":\"%s\"}",
           static_cast<unsigned int>(kProtocolVersion),
           static_cast<unsigned long>(command_session_id),
           static_cast<unsigned long>(request_id), action);
  command_characteristic->setValue(message);
  command_characteristic->notify();
  return true;
}

bool bleClearBonds() {
#if defined(CONFIG_BLUEDROID_ENABLED)
  int count = esp_ble_get_bond_device_num();
  if (count == 0) {
    return true;
  }
  if (count < 0) {
    Serial.printf("[ble] failed to count bonds: %d\n", count);
    return false;
  }

  auto* devices = static_cast<esp_ble_bond_dev_t*>(
      malloc(sizeof(esp_ble_bond_dev_t) * count));
  if (devices == nullptr) {
    Serial.println("[ble] failed to allocate bond list");
    return false;
  }

  const esp_err_t list_result =
      esp_ble_get_bond_device_list(&count, devices);
  if (list_result != ESP_OK) {
    Serial.printf("[ble] failed to read bonds: %d\n", list_result);
    free(devices);
    return false;
  }

  bool cleared = true;
  for (int i = 0; i < count; ++i) {
    const esp_err_t remove_result =
        esp_ble_remove_bond_device(devices[i].bd_addr);
    if (remove_result != ESP_OK) {
      Serial.printf("[ble] failed to remove bond %d: %d\n", i,
                    remove_result);
      cleared = false;
    }
  }
  free(devices);
  return cleared;
#elif defined(CONFIG_NIMBLE_ENABLED)
  const int result = ble_store_clear();
  if (result != 0) {
    Serial.printf("[ble] failed to clear NimBLE bonds: %d\n", result);
    return false;
  }
  return true;
#else
  Serial.println("[ble] no supported BLE host stack");
  return false;
#endif
}
