// Copyright (C) 2024, Mark Qvist
//
// Secure WiFi remote-control support for ESP32-class boards. This starts from
// an authenticated session and only exposes the raw KISS control tunnel once
// the controller has proven knowledge of the configured remote secret.

#ifndef REMOTE_H
#define REMOTE_H

#include <WiFi.h>
#include <mbedtls/md.h>
#include <string.h>

#if CONFIG_IDF_TARGET_ESP32
  #include "esp32/rom/rtc.h"
#elif CONFIG_IDF_TARGET_ESP32S2
  #include "esp32s2/rom/rtc.h"
#elif CONFIG_IDF_TARGET_ESP32C3
  #include "esp32c3/rom/rtc.h"
#elif CONFIG_IDF_TARGET_ESP32S3
  #include "esp32s3/rom/rtc.h"
#else
  #error Target CONFIG_IDF_TARGET is not supported
#endif

#define WIFI_UPDATE_INTERVAL_MS 500
#define WR_SOCKET_TIMEOUT 6
#define WR_READ_TIMEOUT_MS 6500
#define WR_RECONNECT_INTERVAL_MS 10000
#define WR_CHANNEL_DEFAULT 6

#define WIFI_OFF  0x00
#define WR_WIFI_AP  0x01
#define WR_WIFI_STA 0x02

#define WR_STATE_OFF           0x00
#define WR_STATE_ON            0x01
#define WR_STATE_CONNECTED     0x02
#define WR_STATE_AUTHENTICATED 0x03

#define WR_AUTH_NONCE_LEN 16
#define WR_AUTH_KEY_LEN   32
#define WR_AUTH_LINE_MAX  96

#define WR_SECURITY_KEY_SET        0x01
#define WR_SECURITY_CONNECTED      0x02
#define WR_SECURITY_AUTHENTICATED  0x04
#define WR_SECURITY_WIFI_ENABLED   0x08
#define WR_SECURITY_AUTH_REQUIRED  0x10
#define WR_SECURITY_LINK_UP        0x20

void serial_write(uint8_t byte);
void escaped_serial_write(uint8_t byte);
extern void host_disconnected();

uint32_t wifi_update_interval_ms = WIFI_UPDATE_INTERVAL_MS;
uint32_t last_wifi_update = 0;
uint32_t wr_last_connect_try = 0;
uint32_t wr_last_read = 0;

WiFiClient connection;
WiFiServer remote_listener(7633, 1);
IPAddress ap_ip(10, 0, 0, 1);
IPAddress ap_nm(255, 255, 255, 0);
IPAddress wr_device_ip;
char wr_hostname[10];
wl_status_t wr_wifi_status = WL_IDLE_STATUS;

uint8_t wifi_mode = WIFI_OFF;
uint8_t wr_state = WR_STATE_OFF;
uint8_t wr_channel = WR_CHANNEL_DEFAULT;
bool wifi_init_ran = false;
bool wifi_initialized = false;

char wr_ssid[33];
char wr_psk[33];
uint8_t wr_auth_key[WR_AUTH_KEY_LEN];
bool wr_auth_key_configured = false;
bool wr_authenticated = false;
char wr_auth_line[WR_AUTH_LINE_MAX];
uint8_t wr_auth_line_len = 0;
uint8_t wr_nonce[WR_AUTH_NONCE_LEN];

uint8_t wifi_remote_mode() { return wifi_mode; }
bool wifi_is_connected() { return (wr_wifi_status == WL_CONNECTED); }
bool wifi_host_is_connected() { return connection && connection.connected(); }
bool wifi_remote_authenticated() { return wr_authenticated && wifi_host_is_connected(); }

void wifi_dbg(const char *msg) {
  Serial.print("[WiFi] ");
  Serial.println(msg);
}

uint8_t wr_conf_read(uint16_t addr) {
  return EEPROM.read(config_addr(addr));
}

void wr_conf_write(uint16_t addr, uint8_t value) {
  EEPROM.write(config_addr(addr), value);
}

void wr_conf_commit() {
  EEPROM.commit();
}

void wr_clear_region(uint16_t addr, size_t len, uint8_t value = 0x00) {
  for (size_t i = 0; i < len; i++) {
    wr_conf_write(addr + i, value);
  }
  wr_conf_commit();
}

void wr_load_string(uint16_t addr, char *buffer, size_t size) {
  size_t limit = size - 1;
  for (size_t i = 0; i < limit; i++) {
    uint8_t value = wr_conf_read(addr + i);
    if (value == 0xFF) value = 0x00;
    buffer[i] = value;
  }
  buffer[limit] = 0x00;
}

void wr_save_string(uint16_t addr, const uint8_t *data, size_t len, size_t max_len) {
  size_t bounded = len;
  if (bounded > max_len) bounded = max_len;
  for (size_t i = 0; i < max_len; i++) {
    uint8_t value = 0x00;
    if (i < bounded) value = data[i];
    wr_conf_write(addr + i, value);
  }
  wr_conf_commit();
}

void wr_load_key() {
  wr_auth_key_configured = false;
  for (size_t i = 0; i < WR_AUTH_KEY_LEN; i++) {
    uint8_t value = wr_conf_read(ADDR_CONF_RKEY + i);
    if (value == 0xFF) value = 0x00;
    wr_auth_key[i] = value;
    if (value != 0x00) {
      wr_auth_key_configured = true;
    }
  }
}

void wr_sha256(const uint8_t *data, size_t len, uint8_t out[WR_AUTH_KEY_LEN]) {
  mbedtls_md_context_t ctx;
  mbedtls_md_type_t md_type = MBEDTLS_MD_SHA256;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(md_type), 0);
  mbedtls_md_starts(&ctx);
  mbedtls_md_update(&ctx, data, len);
  mbedtls_md_finish(&ctx, out);
  mbedtls_md_free(&ctx);
}

void wr_hmac_sha256(const uint8_t *key, size_t key_len, const uint8_t *data, size_t len, uint8_t out[WR_AUTH_KEY_LEN]) {
  mbedtls_md_context_t ctx;
  const mbedtls_md_info_t *info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, info, 1);
  mbedtls_md_hmac_starts(&ctx, key, key_len);
  mbedtls_md_hmac_update(&ctx, data, len);
  mbedtls_md_hmac_finish(&ctx, out);
  mbedtls_md_free(&ctx);
}

void wr_store_hashed_secret(const uint8_t *data, size_t len) {
  uint8_t digest[WR_AUTH_KEY_LEN];
  memset(digest, 0x00, sizeof(digest));
  if (len > 0) {
    wr_sha256(data, len, digest);
  }

  for (size_t i = 0; i < WR_AUTH_KEY_LEN; i++) {
    wr_conf_write(ADDR_CONF_RKEY + i, digest[i]);
    wr_auth_key[i] = digest[i];
  }
  wr_conf_commit();

  wr_auth_key_configured = false;
  for (size_t i = 0; i < WR_AUTH_KEY_LEN; i++) {
    if (wr_auth_key[i] != 0x00) {
      wr_auth_key_configured = true;
      break;
    }
  }
}

void wr_hex_encode(const uint8_t *src, size_t len, char *dst) {
  static const char *hex = "0123456789abcdef";
  for (size_t i = 0; i < len; i++) {
    dst[i * 2] = hex[(src[i] >> 4) & 0x0F];
    dst[i * 2 + 1] = hex[src[i] & 0x0F];
  }
  dst[len * 2] = 0x00;
}

int8_t wr_hex_nibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

bool wr_hex_decode(const char *src, uint8_t *dst, size_t dst_len) {
  for (size_t i = 0; i < dst_len; i++) {
    int8_t hi = wr_hex_nibble(src[i * 2]);
    int8_t lo = wr_hex_nibble(src[i * 2 + 1]);
    if (hi < 0 || lo < 0) return false;
    dst[i] = (hi << 4) | lo;
  }
  return true;
}

uint8_t wifi_security_flags() {
  uint8_t flags = 0x00;
  if (wr_auth_key_configured) flags |= WR_SECURITY_KEY_SET;
  if (wifi_host_is_connected()) flags |= WR_SECURITY_CONNECTED;
  if (wifi_remote_authenticated()) flags |= WR_SECURITY_AUTHENTICATED;
  if (wifi_mode != WIFI_OFF) flags |= WR_SECURITY_WIFI_ENABLED;
  if (wr_auth_key_configured) flags |= WR_SECURITY_AUTH_REQUIRED;
  if (wifi_is_connected()) flags |= WR_SECURITY_LINK_UP;
  return flags;
}

void kiss_indicate_wifi_mode() {
  serial_write(FEND);
  serial_write(CMD_WIFI_MODE);
  serial_write(wifi_mode);
  serial_write(FEND);
}

void kiss_indicate_wifi_channel() {
  serial_write(FEND);
  serial_write(CMD_WIFI_CHN);
  serial_write(wr_channel);
  serial_write(FEND);
}

void kiss_indicate_wifi_ip() {
  serial_write(FEND);
  serial_write(CMD_WIFI_IP);
  uint8_t ip_bytes[4];
  if (wifi_is_connected()) {
    for (uint8_t i = 0; i < 4; i++) {
      ip_bytes[i] = wr_device_ip[i];
    }
  } else {
    for (uint8_t i = 0; i < 4; i++) {
      ip_bytes[i] = wr_conf_read(ADDR_CONF_IP + i);
    }
  }
  for (uint8_t i = 0; i < 4; i++) {
    escaped_serial_write(ip_bytes[i]);
  }
  serial_write(FEND);
}

void kiss_indicate_wifi_nm() {
  serial_write(FEND);
  serial_write(CMD_WIFI_NM);
  for (uint8_t i = 0; i < 4; i++) {
    escaped_serial_write(wr_conf_read(ADDR_CONF_NM + i));
  }
  serial_write(FEND);
}

void kiss_indicate_wifi_ssid() {
  serial_write(FEND);
  serial_write(CMD_WIFI_SSID);
  for (uint8_t i = 0; i < 32; i++) {
    escaped_serial_write((uint8_t)wr_ssid[i]);
  }
  serial_write(FEND);
}

void kiss_indicate_wifi_psk_state() {
  bool configured = false;
  for (uint8_t i = 0; i < 32; i++) {
    if (wr_psk[i] != 0x00) {
      configured = true;
      break;
    }
  }
  serial_write(FEND);
  serial_write(CMD_WIFI_PSK);
  serial_write(configured ? 0x01 : 0x00);
  serial_write(FEND);
}

void kiss_indicate_wifi_key_state() {
  serial_write(FEND);
  serial_write(CMD_WIFI_KEY);
  serial_write(wr_auth_key_configured ? 0x01 : 0x00);
  serial_write(FEND);
}

void kiss_indicate_wifi_security() {
  serial_write(FEND);
  serial_write(CMD_WIFI_SEC);
  serial_write(wifi_security_flags());
  serial_write(FEND);
}

void wifi_remote_reset_auth_state() {
  wr_authenticated = false;
  wr_auth_line_len = 0;
  memset(wr_auth_line, 0x00, sizeof(wr_auth_line));
  memset(wr_nonce, 0x00, sizeof(wr_nonce));
}

void wifi_remote_close_all() {
  bool had_connection = wifi_host_is_connected();
  if (connection) {
    connection.stop();
  }

  WiFiClient client = remote_listener.available();
  while (client) {
    client.stop();
    client = remote_listener.available();
  }

  wifi_remote_reset_auth_state();
  wr_state = wifi_initialized ? WR_STATE_ON : WR_STATE_OFF;

  if (had_connection) {
    host_disconnected();
  }
}

void wifi_remote_stop() {
  wifi_remote_close_all();
  remote_listener.end();
  WiFi.softAPdisconnect(true);
  WiFi.disconnect(true, true);
  WiFi.mode(WIFI_MODE_NULL);
  wifi_initialized = false;
  wr_state = WR_STATE_OFF;
}

void wifi_remote_start_ap() {
  WiFi.mode(WIFI_AP);
  if (wr_ssid[0] != 0x00) {
    if (wr_psk[0] != 0x00) { WiFi.softAP(wr_ssid, wr_psk, wr_channel); }
    else                   { WiFi.softAP(wr_ssid, nullptr, wr_channel); }
  } else {
    if (wr_psk[0] != 0x00) { WiFi.softAP(bt_devname, wr_psk, wr_channel); }
    else                   { WiFi.softAP(bt_devname, nullptr, wr_channel); }
  }
  delay(150);
  WiFi.softAPConfig(ap_ip, ap_ip, ap_nm);
  wifi_initialized = true;
}

void wifi_remote_start_sta() {
  WiFi.mode(WIFI_STA);

  uint8_t ip[4]; bool ip_ok = true;
  for (uint8_t i = 0; i < 4; i++) {
    ip[i] = wr_conf_read(ADDR_CONF_IP + i);
  }
  if ((ip[0] == 0x00 && ip[1] == 0x00 && ip[2] == 0x00 && ip[3] == 0x00) ||
      (ip[0] == 0xFF && ip[1] == 0xFF && ip[2] == 0xFF && ip[3] == 0xFF)) {
    ip_ok = false;
  }

  uint8_t nm[4]; bool nm_ok = true;
  for (uint8_t i = 0; i < 4; i++) {
    nm[i] = wr_conf_read(ADDR_CONF_NM + i);
  }
  if ((nm[0] == 0x00 && nm[1] == 0x00 && nm[2] == 0x00 && nm[3] == 0x00) ||
      (nm[0] == 0xFF && nm[1] == 0xFF && nm[2] == 0xFF && nm[3] == 0xFF)) {
    nm_ok = false;
  }

  if (ip_ok && nm_ok) {
    IPAddress sta_ip(ip[0], ip[1], ip[2], ip[3]);
    IPAddress sta_nm(nm[0], nm[1], nm[2], nm[3]);
    WiFi.config(sta_ip, sta_ip, sta_nm);
  }

  delay(100);
  if (wr_ssid[0] != 0x00) {
    if (wr_psk[0] != 0x00) { WiFi.begin(wr_ssid, wr_psk); }
    else                   { WiFi.begin(wr_ssid); }
  }

  delay(500);
  wr_wifi_status = WiFi.status();
  wifi_initialized = true;
  wr_last_connect_try = millis();
}

void wifi_remote_start() {
  if      (wifi_mode == WR_WIFI_AP)  { wifi_remote_start_ap(); }
  else if (wifi_mode == WR_WIFI_STA) { wifi_remote_start_sta(); }
  else                               { wifi_remote_stop(); return; }

  remote_listener.end();
  if (wifi_initialized && wr_auth_key_configured) {
    remote_listener.begin();
    remote_listener.setTimeout(WR_SOCKET_TIMEOUT);
    wr_state = WR_STATE_ON;
  } else {
    wr_state = wifi_initialized ? WR_STATE_ON : WR_STATE_OFF;
  }
}

void wifi_remote_init() {
  memcpy(wr_hostname, bt_devname, 5);
  memcpy(wr_hostname + 5, bt_devname + 6, 4);
  wr_hostname[9] = 0x00;

  wr_load_string(ADDR_CONF_SSID, wr_ssid, sizeof(wr_ssid));
  wr_load_string(ADDR_CONF_PSK, wr_psk, sizeof(wr_psk));
  wr_load_key();

  uint8_t persisted_mode = EEPROM.read(eeprom_addr(ADDR_CONF_WIFI));
  if (persisted_mode == WR_WIFI_AP || persisted_mode == WR_WIFI_STA) {
    wifi_mode = persisted_mode;
  } else {
    wifi_mode = WIFI_OFF;
  }

  wr_channel = EEPROM.read(eeprom_addr(ADDR_CONF_WCHN));
  if (wr_channel < 1 || wr_channel > 14) {
    wr_channel = WR_CHANNEL_DEFAULT;
  }

  WiFi.softAPdisconnect(true);
  WiFi.disconnect(true, true);
  WiFi.mode(WIFI_MODE_NULL);
  WiFi.setHostname(wr_hostname);

  wifi_remote_reset_auth_state();
  wifi_remote_start();
  wifi_init_ran = true;
}

void wifi_conf_save_mode(uint8_t mode) {
  if (mode != WIFI_OFF && mode != WR_WIFI_AP && mode != WR_WIFI_STA) {
    mode = WIFI_OFF;
  }
  EEPROM.write(eeprom_addr(ADDR_CONF_WIFI), mode);
  EEPROM.commit();
  wifi_mode = mode;
  if (wifi_init_ran) {
    wifi_remote_init();
  }
}

void wifi_conf_save_channel(uint8_t channel) {
  if (channel < 1 || channel > 14) {
    channel = WR_CHANNEL_DEFAULT;
  }
  EEPROM.write(eeprom_addr(ADDR_CONF_WCHN), channel);
  EEPROM.commit();
  wr_channel = channel;
  if (wifi_init_ran) {
    wifi_remote_init();
  }
}

void wifi_conf_save_ssid(const uint8_t *data, size_t len) {
  wr_save_string(ADDR_CONF_SSID, data, len, 32);
  wr_load_string(ADDR_CONF_SSID, wr_ssid, sizeof(wr_ssid));
  if (wifi_init_ran) {
    wifi_remote_init();
  }
}

void wifi_conf_save_psk(const uint8_t *data, size_t len) {
  wr_save_string(ADDR_CONF_PSK, data, len, 32);
  wr_load_string(ADDR_CONF_PSK, wr_psk, sizeof(wr_psk));
  if (wifi_init_ran) {
    wifi_remote_init();
  }
}

void wifi_conf_save_ip(const uint8_t *data) {
  for (uint8_t i = 0; i < 4; i++) {
    wr_conf_write(ADDR_CONF_IP + i, data[i]);
  }
  wr_conf_commit();
  if (wifi_init_ran) {
    wifi_remote_init();
  }
}

void wifi_conf_save_nm(const uint8_t *data) {
  for (uint8_t i = 0; i < 4; i++) {
    wr_conf_write(ADDR_CONF_NM + i, data[i]);
  }
  wr_conf_commit();
  if (wifi_init_ran) {
    wifi_remote_init();
  }
}

void wifi_conf_clear_remote_key() {
  wr_store_hashed_secret(nullptr, 0);
  if (wifi_init_ran) {
    wifi_remote_init();
  }
}

void wifi_conf_save_remote_key(const uint8_t *data, size_t len) {
  wr_store_hashed_secret(data, len);
  if (wifi_init_ran) {
    wifi_remote_init();
  }
}

void wr_build_auth_token(uint8_t out[WR_AUTH_KEY_LEN]) {
  uint8_t payload[WR_AUTH_NONCE_LEN + DEV_HASH_LEN];
  memcpy(payload, wr_nonce, WR_AUTH_NONCE_LEN);
  memcpy(payload + WR_AUTH_NONCE_LEN, dev_hash, DEV_HASH_LEN);
  wr_hmac_sha256(wr_auth_key, WR_AUTH_KEY_LEN, payload, sizeof(payload), out);
}

void wifi_remote_begin_auth() {
  wifi_remote_reset_auth_state();
  for (uint8_t i = 0; i < WR_AUTH_NONCE_LEN; i++) {
    wr_nonce[i] = (uint8_t)(esp_random() & 0xFF);
  }

  char nonce_hex[(WR_AUTH_NONCE_LEN * 2) + 1];
  char hash_hex[(DEV_HASH_LEN * 2) + 1];
  wr_hex_encode(wr_nonce, WR_AUTH_NONCE_LEN, nonce_hex);
  wr_hex_encode(dev_hash, DEV_HASH_LEN, hash_hex);

  connection.print("WRSEC1 NONCE=");
  connection.print(nonce_hex);
  connection.print(" HASH=");
  connection.print(hash_hex);
  connection.print(" NAME=");
  connection.print(bt_devname);
  connection.print("\n");

  wr_state = WR_STATE_CONNECTED;
  wr_last_read = millis();
}

bool wifi_remote_finish_auth(const char *line) {
  static const char prefix[] = "AUTH ";
  if (strncmp(line, prefix, strlen(prefix)) != 0) {
    return false;
  }

  const char *hex = line + strlen(prefix);
  if (strlen(hex) != WR_AUTH_KEY_LEN * 2) {
    return false;
  }

  uint8_t expected[WR_AUTH_KEY_LEN];
  uint8_t received[WR_AUTH_KEY_LEN];
  wr_build_auth_token(expected);
  if (!wr_hex_decode(hex, received, WR_AUTH_KEY_LEN)) {
    return false;
  }

  if (memcmp(expected, received, WR_AUTH_KEY_LEN) != 0) {
    return false;
  }

  wr_authenticated = true;
  wr_state = WR_STATE_AUTHENTICATED;
  cable_state = CABLE_STATE_CONNECTED;
  display_unblank();
  connection.print("OK\n");
  return true;
}

void wifi_remote_process_auth() {
  while (connection && connection.connected() && connection.available()) {
    char c = (char)connection.read();
    wr_last_read = millis();

    if (c == '\r') {
      continue;
    }

    if (c == '\n') {
      wr_auth_line[wr_auth_line_len] = 0x00;
      if (!wifi_remote_finish_auth(wr_auth_line)) {
        connection.print("ERR\n");
        wifi_remote_close_all();
      }
      return;
    }

    if (wr_auth_line_len >= WR_AUTH_LINE_MAX - 1) {
      connection.print("ERR\n");
      wifi_remote_close_all();
      return;
    }

    wr_auth_line[wr_auth_line_len++] = c;
  }
}

void wifi_remote_check_active() {
  if (millis() - wr_last_read >= WR_READ_TIMEOUT_MS) {
    wifi_remote_close_all();
  }
}

bool wifi_remote_finalize_frame(uint8_t command, uint8_t *data, size_t len) {
  switch (command) {
    case CMD_WIFI_SSID:
      if (len == 1 && data[0] == 0xFF) {
        kiss_indicate_wifi_ssid();
      } else if (len <= 32) {
        wifi_conf_save_ssid(data, len);
        kiss_indicate_wifi_ssid();
      }
      return true;

    case CMD_WIFI_PSK:
      if (len == 1 && data[0] == 0xFF) {
        kiss_indicate_wifi_psk_state();
      } else if (len <= 32) {
        wifi_conf_save_psk(data, len);
        kiss_indicate_wifi_psk_state();
      }
      return true;

    case CMD_WIFI_IP:
      if (len == 1 && data[0] == 0xFF) {
        kiss_indicate_wifi_ip();
      } else if (len == 4) {
        wifi_conf_save_ip(data);
        kiss_indicate_wifi_ip();
      }
      return true;

    case CMD_WIFI_NM:
      if (len == 1 && data[0] == 0xFF) {
        kiss_indicate_wifi_nm();
      } else if (len == 4) {
        wifi_conf_save_nm(data);
        kiss_indicate_wifi_nm();
      }
      return true;

    case CMD_WIFI_KEY:
      if (len == 1 && data[0] == 0xFF) {
        kiss_indicate_wifi_key_state();
      } else if (len > 0 && len <= 32) {
        wifi_conf_save_remote_key(data, len);
        kiss_indicate_wifi_key_state();
        kiss_indicate_wifi_security();
      }
      return true;

    default:
      return false;
  }
}

bool wifi_remote_available() {
  if (!wifi_initialized) {
    return false;
  }

  if (connection) {
    if (connection.connected()) {
      if (!wr_authenticated) {
        if (connection.available()) {
          wifi_remote_process_auth();
        } else {
          wifi_remote_check_active();
        }
        return false;
      }

      if (connection.available()) {
        wr_last_read = millis();
        return true;
      }

      wifi_remote_check_active();
      return false;
    }

    wifi_remote_close_all();
    return false;
  }

  WiFiClient client = remote_listener.available();
  if (!client) {
    return false;
  }

  connection = client;
  wr_last_read = millis();
  display_unblank();

  if (!wr_auth_key_configured) {
    connection.print("ERR NOAUTH\n");
    wifi_remote_close_all();
    return false;
  }

  wifi_remote_begin_auth();
  return false;
}

uint8_t wifi_remote_read() {
  if (wifi_remote_authenticated() && connection.available()) {
    return connection.read();
  }

  if (connection) {
    wifi_remote_close_all();
  }

  return FEND;
}

void wifi_remote_write(uint8_t byte) {
  if (wifi_remote_authenticated()) {
    connection.write(byte);
  }
}

void wifi_update_status() {
  wr_wifi_status = WiFi.status();
  if (wr_wifi_status == WL_CONNECTED) {
    wr_device_ip = WiFi.localIP();
  }
  if (wifi_mode == WR_WIFI_AP && wifi_initialized) {
    wr_device_ip = WiFi.softAPIP();
    wr_wifi_status = WL_CONNECTED;
  }
  if (wifi_init_ran && wifi_mode == WR_WIFI_STA && wr_wifi_status != WL_CONNECTED) {
    if (millis() - wr_last_connect_try >= WR_RECONNECT_INTERVAL_MS) {
      wifi_remote_init();
    }
  }
}

void update_wifi() {
  if (millis() - last_wifi_update >= wifi_update_interval_ms) {
    wifi_update_status();
    last_wifi_update = millis();
  }
}

#endif
