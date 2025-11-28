# 고객님 전용 BTCUSDT 격리 선물 봇 – 2025-11 변경 로그 반영판 (테스트넷)
import ccxt
import pandas as pd
import time
import os
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route('/')
def home():
    return "테스트넷 봇 살아있어요! " + time.strftime('%H:%M')

def run_server():
    app.run(host='0.0.0.0', port=5000)

API_KEY = os.environ.get('API_KEY', '')
API_SECRET = os.environ.get('API_SECRET', '')

SYMBOL = 'BTCUSDT'
TIMEFRAME = '15m'
POSITION_RATIO = 0.10
TRAIL_RATE = 1.5
HARD_SL = -5.0

def run_bot():
    if not API_KEY or not API_SECRET:
        print("API_KEY와 API_SECRET 환경변수를 설정해주세요!")
        return

    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
        'urls': {'api': {'fapi': 'https://testnet.binancefuture.com/fapi/v1'}},
        'options': {'defaultType': 'future'}
    })

    try:
        exchange.fapiPrivate_post_margintype({'symbol': SYMBOL, 'marginType': 'ISOLATED'})
        exchange.fapiPrivate_post_leverage({'symbol': SYMBOL, 'leverage': 1})
        print("테스트넷 격리 1배 설정 완료")
    except Exception as e:
        print("초기 설정:", e)

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("테스트넷 봇 가동 시작! 가상 10,000 USDT로 연습 중 (2025-11 변경 로그 반영)")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    def get_balance():
        return float(exchange.fetch_balance()['USDT']['free'])

    def get_ohlcv():
        raw = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=200)
        df = pd.DataFrame(raw, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df

    def calculate_indicators(df):
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema60'] = df['close'].ewm(span=60, adjust=False).mean()
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        df['rsi'] = 100 - 100 / (1 + gain / loss)
        return df

    def get_position():
        pos = exchange.fapiPrivate_v2_get_positionrisk({'symbol': SYMBOL})[0]
        amt = float(pos['positionAmt'])
        if amt == 0:
            return None, 0, 0
        entry = float(pos['entryPrice'])
        side = 'LONG' if amt > 0 else 'SHORT'
        return side, abs(amt), entry

    while True:
        try:
            df = get_ohlcv()
            df = calculate_indicators(df)
            last = df.iloc[-2]
            price = last['close']
            balance = get_balance()
            side, qty, entry_price = get_position()

            if side:
                if side == 'LONG':
                    pnl = (price / entry_price - 1) * 100
                    if pnl <= HARD_SL:
                        exchange.create_market_sell_order(SYMBOL, qty)
                        exchange.fapiPrivate_delete_allopenorders({'symbol': SYMBOL})
                        print(f"[{time.strftime('%H:%M')}] HARD SL LONG 청산 {pnl:.2f}%")
                else:
                    pnl = (1 - price / entry_price) * 100
                    if pnl <= HARD_SL:
                        exchange.create_market_buy_order(SYMBOL, qty)
                        exchange.fapiPrivate_delete_allopenorders({'symbol': SYMBOL})
                        print(f"[{time.strftime('%H:%M')}] HARD SL SHORT 청산 {pnl:.2f}%")

            elif side is None:
                usdt_to_use = balance * POSITION_RATIO
                quantity = round(usdt_to_use / price, 3)
                if quantity >= 0.001:
                    if last['ema20'] > last['ema60'] and price > last['ema20'] and last['rsi'] < 68:
                        exchange.create_market_buy_order(SYMBOL, quantity)
                        exchange.fapiPrivate_post_algoorder({
                            'symbol': SYMBOL,
                            'side': 'SELL',
                            'type': 'TRAILING_STOP_MARKET',
                            'quantity': quantity,
                            'callbackRate': TRAIL_RATE,
                            'workingType': 'MARK_PRICE'
                        })
                        print(f"[{time.strftime('%H:%M')}] LONG 진입 {quantity} BTC (algo trailing 설정)")

                    elif last['ema20'] < last['ema60'] and price < last['ema20'] and last['rsi'] > 32:
                        exchange.create_market_sell_order(SYMBOL, quantity)
                        exchange.fapiPrivate_post_algoorder({
                            'symbol': SYMBOL,
                            'side': 'BUY',
                            'type': 'TRAILING_STOP_MARKET',
                            'quantity': quantity,
                            'callbackRate': TRAIL_RATE,
                            'workingType': 'MARK_PRICE'
                        })
                        print(f"[{time.strftime('%H:%M')}] SHORT 진입 {quantity} BTC (algo trailing 설정)")

            time.sleep(30)

        except Exception as e:
            print(f"[{time.strftime('%H:%M')}] 에러: {e}")
            time.sleep(30)

if __name__ == '__main__':
    Thread(target=run_bot, daemon=True).start()
    run_server()
