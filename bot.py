import time
import requests
import logging
import pandas as pd

# ===== CẤU HÌNH NGƯỜI DÙNG =====
TELEGRAM_BOT_TOKEN = "8357423002:AAGUgGhEQb4vxPUp88PYEOKJfl7HIDzPfpk"  # BotFather cấp
TELEGRAM_CHAT_ID = "8332206639"  # Chat ID cá nhân hoặc nhóm
POLL_INTERVAL = 300  # 5 phút giữa 2 lần kiểm tra

# 🔔 Các cảnh báo giá cụ thể
ALERTS = [
    {"symbol": "BTCUSDT", "threshold": 107348, "direction": "above"},
    {"symbol": "BTCUSDT", "threshold": 103628, "direction": "below"},
    {"symbol": "ETHUSDT", "threshold": 3883, "direction": "above"},
    {"symbol": "ETHUSDT", "threshold": 3522, "direction": "below"},
]

# 🔔 Các khung EMA cần theo dõi
EMA_ALERTS = [
    {"symbol": "BTCUSDT", "interval": "1h"},
    {"symbol": "BTCUSDT", "interval": "4h"},
    {"symbol": "BTCUSDT", "interval": "1d"},
    {"symbol": "ETHUSDT", "interval": "1h"},
    {"symbol": "ETHUSDT", "interval": "4h"},
    {"symbol": "ETHUSDT", "interval": "1d"},
]

BINANCE_URL_PRICE = "https://fapi.binance.com/fapi/v1/premiumIndex"
BINANCE_URL_KLINES = "https://fapi.binance.com/fapi/v1/klines"
logging.basicConfig(filename="alerts.log", level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")


# ===== HÀM CHÍNH =====

def send_telegram(msg):
    """Gửi tin nhắn Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        logging.error(f"Lỗi gửi Telegram: {e}")


def get_price(symbol):
    """Lấy giá mark price hiện tại"""
    try:
        r = requests.get(BINANCE_URL_PRICE, params={"symbol": symbol}, timeout=10)
        r.raise_for_status()
        return float(r.json()["markPrice"])
    except Exception as e:
        logging.error(f"Lỗi lấy giá {symbol}: {e}")
        return None


def get_ema_cross(symbol, interval, length=21):
    """Kiểm tra xem giá vừa cắt EMA21"""
    try:
        params = {"symbol": symbol, "interval": interval, "limit": 100}
        r = requests.get(BINANCE_URL_KLINES, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        df = pd.DataFrame(data, columns=[
            "time", "open", "high", "low", "close",
            "volume", "close_time", "qav", "trades",
            "tbbav", "tbqav", "ignore"
        ])
        df["close"] = df["close"].astype(float)
        df["ema"] = df["close"].ewm(span=length).mean()

        # Hai nến cuối
        prev_close, curr_close = df["close"].iloc[-2], df["close"].iloc[-1]
        prev_ema, curr_ema = df["ema"].iloc[-2], df["ema"].iloc[-1]

        crossed_up = prev_close < prev_ema and curr_close > curr_ema
        crossed_down = prev_close > prev_ema and curr_close < curr_ema

        if crossed_up:
            return f"🔼 {symbol} ({interval}) vừa CẮT LÊN EMA{length} – Giá: {curr_close:.2f}"
        elif crossed_down:
            return f"🔽 {symbol} ({interval}) vừa CẮT XUỐNG EMA{length} – Giá: {curr_close:.2f}"
        else:
            return None
    except Exception as e:
        logging.error(f"Lỗi tính EMA {symbol} {interval}: {e}")
        return None


def main():
    last_price_state = {a["symbol"] + str(a["threshold"]) + a["direction"]: None for a in ALERTS}
    last_ema_state = {f"{a['symbol']}_{a['interval']}": None for a in EMA_ALERTS}
    logging.info("Bắt đầu theo dõi giá và EMA...")

    while True:
        # 1️⃣ Kiểm tra các ngưỡng giá cụ thể
        for alert in ALERTS:
            price = get_price(alert["symbol"])
            if price is None:
                continue

            key = alert["symbol"] + str(alert["threshold"]) + alert["direction"]
            direction = alert["direction"]
            threshold = alert["threshold"]
            was_above = last_price_state[key]
            is_above = price > threshold

            # Phát cảnh báo
            if direction == "above" and (was_above is not True) and is_above:
                msg = f"🔔 {alert['symbol']} vượt lên {threshold:.2f} → Giá hiện tại: {price:.2f}"
                send_telegram(msg)
                logging.info(msg)
            elif direction == "below" and (was_above is not False) and not is_above:
                msg = f"🔔 {alert['symbol']} cắt xuống {threshold:.2f} → Giá hiện tại: {price:.2f}"
                send_telegram(msg)
                logging.info(msg)

            last_price_state[key] = is_above

        # 2️⃣ Kiểm tra cắt EMA21
        for ema_alert in EMA_ALERTS:
            key = f"{ema_alert['symbol']}_{ema_alert['interval']}"
            msg = get_ema_cross(ema_alert["symbol"], ema_alert["interval"])
            if msg and msg != last_ema_state[key]:
                send_telegram(msg)
                logging.info(msg)
                last_ema_state[key] = msg

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
