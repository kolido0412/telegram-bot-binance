import logging
import requests
import pandas as pd
from datetime import datetime, timezone
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# ===== CẤU HÌNH NGƯỜI DÙNG =====
TELEGRAM_BOT_TOKEN = "8357423002:AAGUgGhEQb4vxPUp88PYEOKJfl7HIDzPfpk"
TELEGRAM_CHAT_ID = "8332206639"
SYMBOLS = ["BTCUSDT"]
INTERVALS = ["15m", "30m"]  # Check time
BINANCE_URL_KLINES = "https://fapi.binance.com/fapi/v1/klines"

# Logging
logging.basicConfig(filename="Alerts_Bot_Volume_Candle.log", level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ===== SESSION CÓ RETRY =====
session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=1.5,
    status_forcelist=[429, 500, 502, 503, 504],
)
session.mount("https://", HTTPAdapter(max_retries=retries))

# ===== HỖ TRỢ GỬI TELEGRAM =====
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    try:
        r = session.post(url, json=payload, timeout=15)
        r.raise_for_status()
        logger.info(f"Telegram sent: {msg}")
    except Exception as e:
        logger.error(f"Lỗi gửi Telegram: {e} | msg: {msg}")

# ===== LẤY DỮ LIỆU KLINES =====
def fetch_klines(symbol, interval, limit=400):
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = session.get(BINANCE_URL_KLINES, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close",
            "volume", "close_time", "qav", "trades",
            "tbbav", "tbqav", "ignore"
        ])
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df
    except Exception as e:
        logger.error(f"[fetch_klines] Lỗi lấy klines {symbol} {interval}: {e}")
        return None

# ===== TÍNH TOÁN CHỈ BÁO THEO LOGIC CANDLE/VOLUME =====
def compute_signals(df):
    if df is None or len(df) < 50:
        return None

    df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["ema233"] = df["close"].ewm(span=233, adjust=False).mean()
    df["vol89"] = df["volume"].rolling(window=89, min_periods=1).mean()
    df["candle"] = (df["close"] - df["open"]).abs()
    df["can89"] = df["candle"].rolling(window=89, min_periods=1).mean()

    idx = -2
    row = df.iloc[idx]

    close = row["close"]
    openp = row["open"]
    ema21 = row["ema21"]
    ema233 = row["ema233"]
    vol = row["volume"]
    vol89 = row["vol89"]
    candle = row["candle"]
    can89 = row["can89"]

    conbuy = (
        (close > openp)
        and (close > ema21)
        and (close > ema233)
        and ((close - ema21) < 2 * candle)
        and (vol > vol89)
        and (vol > 2.1 * vol89)
        and (candle > 2.1 * can89)
    )

    consell = (
        (close < openp)
        and (close < ema21)
        and (close < ema233)
        and ((ema21 - close) < 2 * candle)
        and (vol > vol89)
        and (vol > 2.1 * vol89)
        and (candle > 2.1 * can89)
    )

    return {
        "time": row["close_time"],
        "close": close,
        "open": openp,
        "ema21": ema21,
        "ema233": ema233,
        "volume": vol,
        "vol89": vol89,
        "candle": candle,
        "can89": can89,
        "conbuy": bool(conbuy),
        "consell": bool(consell)
    }

# ===== LẤY GIÁ MỞ CỬA ĐẦU NGÀY =====
def get_first_open_price(symbol):
    try:
        now = datetime.now(timezone.utc)
        start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        start_ts = int(start_of_day.timestamp() * 1000)
        end_ts = start_ts + 2 * 60 * 60 * 1000

        params = {
            "symbol": symbol,
            "interval": "1h",
            "startTime": start_ts,
            "endTime": end_ts,
            "limit": 2
        }
        r = session.get(BINANCE_URL_KLINES, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if len(data) > 0:
            open_price = float(data[0][1])
            return open_price
        return None
    except Exception as e:
        logger.error(f"[get_first_open_price] Lỗi {symbol}: {e}")
        return None

# ===== MAIN CHỈ CHẠY 1 LẦN =====
def main():
    logger.info("Start Bot - Check candle 15m + 30m và Open Price")
    last_signal = {symbol: {interval: None for interval in INTERVALS} for symbol in SYMBOLS}
    last_open_price = {}
    last_cross_open_state = {}

    for symbol in SYMBOLS:
        # --- Giá mở cửa đầu ngày ---
        first_open = get_first_open_price(symbol)
        if first_open:
            last_open_price[symbol] = first_open
            last_cross_open_state[symbol] = None
            # send_telegram(f"📊 {symbol} – Giá mở cửa đầu ngày (UTC): {first_open}")
            logger.info(f"{symbol} Open Price UTC: {first_open}")

        # --- Cảnh báo BUY/SELL candle/volume ---
        for interval in INTERVALS:
            df = fetch_klines(symbol, interval, limit=400)
            if df is None:
                continue
            sig = compute_signals(df)
            if sig is None:
                continue

            now_str = sig["time"].strftime("%Y-%m-%d %H:%M:%S %Z")
            last = last_signal[symbol][interval]

            if sig["conbuy"] and last != "buy":
                msg = f"🔵 BUY Signal\n{symbol} | Interval: {interval}"
                send_telegram(msg)
                logger.info(f"{symbol} BUY alert sent at {now_str} | Interval: {interval}")
                last_signal[symbol][interval] = "buy"

            elif sig["consell"] and last != "sell":
                msg = f"🔴 SELL Signal\n{symbol} | Interval: {interval}"
                send_telegram(msg)
                logger.info(f"{symbol} SELL alert sent at {now_str} | Interval: {interval}")
                last_signal[symbol][interval] = "sell"
            else:
                last_signal[symbol][interval] = last

if __name__ == "__main__":
    main()

