# -*- coding: utf-8 -*-
from binance.um_futures import UMFutures
import pandas as pd
import time
import os
import logging
from flask import Flask
from threading import Thread

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Flask 애플리케이션 설정
app = Flask(__name__)

@app.route('/')
def home():
    """웹 서버가 정상 작동 중임을 알리는 기본 엔드포인트."""
    return f"테스트넷 봇 살아있어요! 현재 시간: {time.strftime('%Y-%m-%d %H:%M:%S')}"

def run_server():
    """Flask 서버를 별도의 스레드에서 실행합니다."""
    app.run(host='0.0.0.0', port=5000)

# 1. 환경 변수 설정
API_KEY = os.environ.get('API_KEY', '')
API_SECRET = os.environ.get('API_SECRET', '')

# 2. 트레이딩 파라미터
SYMBOL = 'BTCUSDT'
TIMEFRAME = '15m'
POSITION_RATIO = 0.10
TRAIL_RATE = 1.5
HARD_SL = -5.0

def run_bot():
    """메인 트레이딩 로직을 실행합니다."""
    if not API_KEY or not API_SECRET:
        logger.error("🚨 오류: API_KEY와 API_SECRET 환경변수를 설정해주세요!")
        return

    # 테스트넷 클라이언트 초기화
    client = UMFutures(
        key=API_KEY,
        secret=API_SECRET,
        base_url='https://testnet.binancefuture.com'
    )

    # 3. 초기 설정: 격리 마진 및 레버리지 설정
    try:
        client.change_margin_type(symbol=SYMBOL, marginType='ISOLATED')
        logger.info("✅ 격리 마진 모드 설정 완료")
    except Exception as e:
        logger.warning(f"⚠️ 마진 모드 설정 실패 (무시 가능): {e}")

    try:
        client.change_leverage(symbol=SYMBOL, leverage=1)
        logger.info("✅ 레버리지 1배 설정 완료")
    except Exception as e:
        logger.warning(f"⚠️ 레버리지 설정 실패 (무시 가능): {e}")

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info(f"🤖 BTCUSDT 테스트넷 봇 가동 시작! (콜백 비율: {TRAIL_RATE}%)")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    def get_balance():
        """사용 가능한 USDT 잔고를 가져옵니다."""
        try:
            account = client.account(recvWindow=5000)
            for asset in account.get('assets', []):
                if asset['asset'] == 'USDT':
                    return float(asset['availableBalance'])
            return 0.0
        except Exception as e:
            logger.error(f"잔고 조회 오류: {e}")
            return 0.0

    def get_ohlcv():
        """OHLCV 데이터를 가져와 DataFrame으로 정리합니다."""
        try:
            klines = client.klines(symbol=SYMBOL, interval=TIMEFRAME, limit=200)
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            return df
        except Exception as e:
            logger.error(f"OHLCV 조회 오류: {e}")
            return pd.DataFrame()

    def calculate_indicators(df):
        """EMA와 RSI 지표를 계산합니다."""
        if df.empty:
            return df
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema60'] = df['close'].ewm(span=60, adjust=False).mean()
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        df['rsi'] = 100 - 100 / (1 + gain / loss.replace(0, 1e-10))
        return df

    def get_position():
        """현재 포지션 정보를 가져옵니다."""
        try:
            positions = client.get_position_risk(symbol=SYMBOL, recvWindow=5000)
            for pos in positions:
                if pos['symbol'] == SYMBOL:
                    amt = float(pos.get('positionAmt', 0))
                    if amt == 0:
                        return None, 0.0, 0.0
                    entry = float(pos.get('entryPrice', 0))
                    side = 'LONG' if amt > 0 else 'SHORT'
                    return side, abs(amt), entry
            return None, 0.0, 0.0
        except Exception as e:
            logger.error(f"포지션 조회 오류: {e}")
            return None, 0.0, 0.0

    def check_open_orders():
        """현재 미체결 주문이 있는지 확인합니다."""
        try:
            orders = client.get_open_orders(symbol=SYMBOL, recvWindow=5000)
            return len(orders) > 0
        except Exception as e:
            logger.warning(f"미체결 주문 조회 오류: {e}")
            return False


    while True:
        try:
            df = get_ohlcv()
            if df.empty or len(df) < 2:
                logger.info(f"[{time.strftime('%H:%M')}] 데이터 부족, 다음 루프 대기.")
                time.sleep(30)
                continue

            df = calculate_indicators(df)
            last_candle = df.iloc[-2]
            current_price = df.iloc[-1]['close']
            last_close = last_candle['close']

            balance = get_balance()
            side, qty, entry_price = get_position()
            has_open_orders = check_open_orders()

            log_message = (
                f"[{time.strftime('%H:%M')}] "
                f"가격: {current_price:.2f} (기준: {last_close:.2f}), "
                f"잔고: {balance:.2f} USDT, "
                f"포지션: {side or '없음'}"
            )

            if side:
                pnl = ((current_price / entry_price - 1) if side == 'LONG' else (1 - current_price / entry_price)) * 100
                log_message += f", PnL: {pnl:.2f}%"
                logger.info(log_message)

                if pnl <= HARD_SL:
                    close_side = 'SELL' if side == 'LONG' else 'BUY'
                    client.new_order(symbol=SYMBOL, side=close_side, type='MARKET', quantity=qty)
                    client.cancel_open_orders(symbol=SYMBOL)
                    logger.warning(f"🚨 HARD SL {side} 청산: PnL {pnl:.2f}%로 종료.")

            elif side is None:
                logger.info(log_message)
                
                if has_open_orders:
                    logger.info("미체결 주문(Trailing Stop 등)이 남아 있어 새로운 진입을 건너뜁니다.")
                else:
                    usdt_to_use = balance * POSITION_RATIO
                    quantity = round(usdt_to_use / current_price, 3)

                    if quantity >= 0.001:
                        if last_candle['ema20'] > last_candle['ema60'] and last_close > last_candle['ema20'] and last_candle['rsi'] < 68:
                            client.new_order(symbol=SYMBOL, side='BUY', type='MARKET', quantity=quantity)
                            client.new_order(
                                symbol=SYMBOL,
                                side='SELL',
                                type='TRAILING_STOP_MARKET',
                                quantity=quantity,
                                callbackRate=TRAIL_RATE
                            )
                            logger.info(f"🚀 LONG 진입: {quantity} BTC (트레일링 스톱 {TRAIL_RATE}% 설정 완료)")

                        elif last_candle['ema20'] < last_candle['ema60'] and last_close < last_candle['ema20'] and last_candle['rsi'] > 32:
                            client.new_order(symbol=SYMBOL, side='SELL', type='MARKET', quantity=quantity)
                            client.new_order(
                                symbol=SYMBOL,
                                side='BUY',
                                type='TRAILING_STOP_MARKET',
                                quantity=quantity,
                                callbackRate=TRAIL_RATE
                            )
                            logger.info(f"🔻 SHORT 진입: {quantity} BTC (트레일링 스톱 {TRAIL_RATE}% 설정 완료)")
                        else:
                            logger.debug("진입 조건 미달")
                    else:
                        logger.info(f"잔고 부족으로 주문 수량({quantity})이 최소 거래량(0.001 BTC) 미만입니다.")

            time.sleep(30)

        except Exception as e:
            logger.error(f"[{time.strftime('%H:%M')}] ❌ 예외 발생: {e}")
            time.sleep(30)

if __name__ == '__main__':
    Thread(target=run_bot, daemon=True).start()
    run_server()
