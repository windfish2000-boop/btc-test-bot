# 고객님 전용 BTCUSDT 격리 선물 봇 – 바이낸스 테스트넷
from binance.um_futures import UMFutures
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

    client = UMFutures(
        key=API_KEY,
        secret=API_SECRET,
        base_url='https://testnet.binancefuture.com'
    )

    try:
        client.change_margin_type(symbol=SYMBOL, marginType='ISOLATED')
        print("격리 마진 모드 설정 완료")
    except Exception as e:
        print("마진 모드 설정:", e)

    try:
        client.change_leverage(symbol=SYMBOL, leverage=1)
        print("레버리지 1배 설정 완료")
    except Exception as e:
        print("레버리지 설정:", e)

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("테스트넷 봇 가동 시작! 가상 USDT로 연습 중")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    def get_balance():
        account = client.account()
        for asset in account['assets']:
            if asset['asset'] == 'USDT':
                return float(asset['availableBalance'])
        return 0

    def get_ohlcv():
        klines = client.klines(symbol=SYMBOL, interval=TIMEFRAME, limit=200)
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
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
        positions = client.get_position_risk(symbol=SYMBOL)
        for pos in positions:
            if pos['symbol'] == SYMBOL:
                amt = float(pos['positionAmt'])
                if amt == 0:
                    return None, 0, 0
                entry = float(pos['entryPrice'])
                side = 'LONG' if amt > 0 else 'SHORT'
                return side, abs(amt), entry
        return None, 0, 0

    while True:
        try:
            df = get_ohlcv()
            df = calculate_indicators(df)
            last = df.iloc[-2]
            price = last['close']
            balance = get_balance()
            side, qty, entry_price = get_position()

            print(f"[{time.strftime('%H:%M')}] 가격: {price:.2f}, 잔고: {balance:.2f} USDT, 포지션: {side or '없음'}")

            if side:
                if side == 'LONG':
                    pnl = (price / entry_price - 1) * 100
                    if pnl <= HARD_SL:
                        client.new_order(symbol=SYMBOL, side='SELL', type='MARKET', quantity=qty)
                        client.cancel_open_orders(symbol=SYMBOL)
                        print(f"[{time.strftime('%H:%M')}] HARD SL LONG 청산 {pnl:.2f}%")
                else:
                    pnl = (1 - price / entry_price) * 100
                    if pnl <= HARD_SL:
                        client.new_order(symbol=SYMBOL, side='BUY', type='MARKET', quantity=qty)
                        client.cancel_open_orders(symbol=SYMBOL)
                        print(f"[{time.strftime('%H:%M')}] HARD SL SHORT 청산 {pnl:.2f}%")

            elif side is None:
                usdt_to_use = balance * POSITION_RATIO
                quantity = round(usdt_to_use / price, 3)
                if quantity >= 0.001:
                    if last['ema20'] > last['ema60'] and price > last['ema20'] and last['rsi'] < 68:
                        client.new_order(symbol=SYMBOL, side='BUY', type='MARKET', quantity=quantity)
                        client.new_order(
                            symbol=SYMBOL,
                            side='SELL',
                            type='TRAILING_STOP_MARKET',
                            quantity=quantity,
                            callbackRate=TRAIL_RATE
                        )
                        print(f"[{time.strftime('%H:%M')}] LONG 진입 {quantity} BTC (trailing 설정)")

                    elif last['ema20'] < last['ema60'] and price < last['ema20'] and last['rsi'] > 32:
                        client.new_order(symbol=SYMBOL, side='SELL', type='MARKET', quantity=quantity)
                        client.new_order(
                            symbol=SYMBOL,
                            side='BUY',
                            type='TRAILING_STOP_MARKET',
                            quantity=quantity,
                            callbackRate=TRAIL_RATE
                        )
                        print(f"[{time.strftime('%H:%M')}] SHORT 진입 {quantity} BTC (trailing 설정)")

            time.sleep(30)

        except Exception as e:
            print(f"[{time.strftime('%H:%M')}] 에러: {e}")
            time.sleep(30)

if __name__ == '__main__':
    Thread(target=run_bot, daemon=True).start()
    run_server()
