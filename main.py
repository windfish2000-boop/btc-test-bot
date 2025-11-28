# -*- coding: utf-8 -*-
import os
import time
import logging
from threading import Thread
from decimal import Decimal, ROUND_DOWN, getcontext

import pandas as pd
from flask import Flask

from binance.um_futures import UMFutures

# --- 로깅 설정 ----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("trading_bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- Flask (간단한 헬스체크) --------------------------------------------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return f"테스트넷 봇 살아있어요! 현재 시간: {time.strftime('%Y-%m-%d %H:%M:%S')}"

def run_server():
    # 개발/테스트용: production에서는 gunicorn / waitress 등 권장
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

# --- 환경 변수 / 설정 --------------------------------------------------------------------
API_KEY = os.environ.get("API_KEY", "")
API_SECRET = os.environ.get("API_SECRET", "")

SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")
TIMEFRAME = os.environ.get("TIMEFRAME", "15m")
POSITION_RATIO = float(os.environ.get("POSITION_RATIO", 0.10))
TRAIL_RATE = float(os.environ.get("TRAIL_RATE", 1.5))
HARD_SL = float(os.environ.get("HARD_SL", -5.0))
BACKUP_TP = float(os.environ.get("BACKUP_TP", 5.0))  # 백업 익절 +5%
BACKUP_SL = float(os.environ.get("BACKUP_SL", -5.0))  # 백업 손절 -5%
TESTNET_BASE_URL = os.environ.get("TESTNET_BASE_URL", "https://testnet.binance.com/fapi")  # 안정적인 테스트넷
CANDLE_INTERVAL = 900  # 15분 = 900초

# 소수점 연산 정밀도
getcontext().prec = 18

# 15분 캔들 동기화 함수
def get_candle_sleep_time():
    """다음 캔들 마감까지의 대기 시간 계산 (초 단위)"""
    now = time.time()
    candle_progress = now % CANDLE_INTERVAL
    sleep_time = CANDLE_INTERVAL - candle_progress
    return sleep_time

# --- 유틸 / 거래소 정보 ------------------------------------------------------------------
def safe_decimal(x):
    return Decimal(str(x))

def get_client():
    if not API_KEY or not API_SECRET:
        logger.error("API_KEY/API_SECRET 미설정. 환경변수를 확인하세요.")
        return None
    logger.info(f"테스트넷 연결: {TESTNET_BASE_URL}")
    client = UMFutures(key=API_KEY, secret=API_SECRET, base_url=TESTNET_BASE_URL)
    return client

def get_exchange_filters(client, symbol):
    """
    심볼의 stepSize(min qty)와 tickSize(가격 소수자리) 등을 시도해서 가져옵니다.
    실패 시 기본값으로 돌아갑니다.
    """
    defaults = {
        "stepSize": Decimal("0.001"),
        "minQty": Decimal("0.001"),
        "tickSize": Decimal("0.01"),
        "pricePrecision": 2
    }
    try:
        info = client.exchange_info()
        for s in info.get("symbols", []):
            if s.get("symbol") == symbol:
                for f in s.get("filters", []):
                    if f.get("filterType") == "LOT_SIZE":
                        step = Decimal(str(f.get("stepSize", "0.001")))
                        minq = Decimal(str(f.get("minQty", "0.001")))
                        defaults["stepSize"] = step
                        defaults["minQty"] = minq
                    if f.get("filterType") == "PRICE_FILTER":
                        tick = f.get("tickSize", "0.01")
                        tick_dec = Decimal(str(tick))
                        defaults["tickSize"] = tick_dec
                        exponent = tick_dec.as_tuple().exponent
                        defaults["pricePrecision"] = int(abs(int(exponent)))
                return defaults
    except Exception as e:
        logger.warning(f"심볼 정보 조회 실패: {e}")
    return defaults

def quantize_qty(qty: Decimal, step: Decimal):
    """거래소 stepSize에 맞춰 내림 반올림 (정확도 보장)"""
    if qty <= 0:
        return Decimal("0")
    # 거래소 규칙에 정확히 부합: (수량 / 스텝).내림 * 스텝
    return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step

def quantize_price(price: Decimal, tick: Decimal):
    """거래소 tickSize에 맞춰 가격 정밀도 조정 (Binance 오류 방지)"""
    if price <= 0 or tick <= 0:
        return price
    # 거래소 규칙: (가격 / 틱).내림 * 틱
    return (price / tick).to_integral_value(rounding=ROUND_DOWN) * tick

# --- 인디케이터 계산 ---------------------------------------------------------------------
def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema60"] = df["close"].ewm(span=60, adjust=False).mean()
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    # loss가 0일때 1e-10로 대체 (ZeroDivision 방지)
    loss = loss.fillna(0).replace(0, 1e-10)  # type: ignore
    df["rsi"] = 100 - 100 / (1 + gain / loss)
    return df

# --- 주요 로직 ---------------------------------------------------------------------------
def run_bot():
    client = get_client()
    if client is None:
        return

    # 시도: 격리/레버리지 (실패해도 계속)
    try:
        client.change_margin_type(symbol=SYMBOL, marginType="ISOLATED")
        logger.info("격리마진 설정 완료")
    except Exception as e:
        logger.warning(f"격리마진 설정 실패: {e}")

    try:
        client.change_leverage(symbol=SYMBOL, leverage=1)
        logger.info("레버리지 1배 설정 완료")
    except Exception as e:
        logger.warning(f"레버리지 설정 실패: {e}")

    filters = get_exchange_filters(client, SYMBOL)
    step_size = filters["stepSize"]
    min_qty = filters["minQty"]
    tick_size = filters["tickSize"]
    logger.info(f"심볼 필터: stepSize={step_size}, minQty={min_qty}, tickSize={tick_size}")

    logger.info("봇 시작: SYMBOL=%s, TIMEFRAME=%s, POSITION_RATIO=%.2f", SYMBOL, TIMEFRAME, POSITION_RATIO)

    def get_balance():
        try:
            acc = client.account(recvWindow=5000)
            for a in acc.get("assets", []):
                if a.get("asset") == "USDT":
                    return float(a.get("availableBalance", 0))
        except Exception as e:
            logger.error(f"잔고 조회 오류: {e}")
        return 0.0

    def get_ohlcv():
        try:
            klines = client.klines(symbol=SYMBOL, interval=TIMEFRAME, limit=200)
            df = pd.DataFrame(klines, columns=[  # type: ignore
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades", "taker_buy_base",
                "taker_buy_quote", "ignore"
            ])
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = df[c].astype(float)
            return df
        except Exception as e:
            logger.error(f"OHLCV 조회 오류: {e}")
            return pd.DataFrame()

    def get_position():
        # positionAmt가 0이면 포지션 없음
        try:
            positions = client.get_position_risk(symbol=SYMBOL, recvWindow=5000)
            for p in positions:
                if p.get("symbol") == SYMBOL:
                    amt = Decimal(str(p.get("positionAmt", "0")))
                    if amt == 0:
                        return None, Decimal("0"), Decimal("0")
                    entry = Decimal(str(p.get("entryPrice", "0")))
                    side = "LONG" if amt > 0 else "SHORT"
                    return side, abs(amt), entry
        except Exception as e:
            logger.error(f"포지션 조회 오류: {e}")
        return None, Decimal("0"), Decimal("0")

    def has_open_orders():
        try:
            orders = client.get_open_orders(symbol=SYMBOL, recvWindow=5000)
            return len(orders) > 0
        except Exception as e:
            logger.error(f"미체결 주문 조회 오류: {e} - 안전 모드로 새 진입 허용")
            return False  # API 오류 시에도 진입 시도

    # 메인 루프
    while True:
        try:
            df = get_ohlcv()
            if df.empty or len(df) < 2:
                logger.info("데이터 부족, 대기")
                time.sleep(get_candle_sleep_time())
                continue

            df = calculate_indicators(df)
            # 마지막 완성 캔들 기준으로 판단 (2개 캔들 연속 확인)
            last_candle = df.iloc[-2]
            prev_candle = df.iloc[-3]
            current_price = Decimal(str(df.iloc[-1]["close"]))
            last_close = Decimal(str(last_candle["close"]))

            balance = Decimal(str(get_balance()))
            side, qty, entry_price = get_position()
            open_orders_exist = has_open_orders()

            # entry_price=0 보호 로직 (ZeroDivision 방지)
            if side and entry_price == 0:
                logger.warning("entry_price=0 → PnL 계산 불가. 포지션 조회 오류로 스킵")
                time.sleep(get_candle_sleep_time())
                continue

            # 상태 로깅
            state_msg = f"가격: {current_price:.2f}, 기준: {last_close:.2f}, 잔고: {balance:.4f} USDT, 포지션: {side or '없음'}"
            if side:
                pnl = ( (current_price / entry_price - 1) if side == "LONG" else (1 - current_price / entry_price) ) * 100
                state_msg += f", PnL: {pnl:.2f}%"
            logger.info(state_msg)

            # HARD SL 체크
            if side:
                pnl = ( (current_price / entry_price - 1) if side == "LONG" else (1 - current_price / entry_price) ) * 100
                if pnl <= HARD_SL:
                    logger.warning("HARD SL 발동: 포지션 청산 시도")
                    try:
                        close_side = "SELL" if side == "LONG" else "BUY"
                        # 시장가로 전량 청산
                        resp = client.new_order(symbol=SYMBOL, side=close_side, type="MARKET", quantity=float(qty))
                        logger.warning(f"HARD SL 청산 주문 체결: {resp}")
                    except Exception as e:
                        logger.error(f"HARD SL 청산 실패: {e}")
                    # 취소 시도 (예외 무시)
                    try:
                        client.cancel_open_orders(symbol=SYMBOL)
                    except Exception as e:
                        logger.debug(f"미체결 주문 취소 실패: {e}")
                    time.sleep(get_candle_sleep_time())
                    continue

            # 포지션 없음 -> 진입 판단
            if side is None:
                # 고아 주문 정리: 포지션이 없으면서 미체결 주문이 있으면 자동 취소
                if open_orders_exist:
                    logger.warning("포지션 없음 + 미체결 주문 존재 (고아 주문) → 자동 취소")
                    try:
                        client.cancel_open_orders(symbol=SYMBOL)
                        logger.info("미체결 주문 모두 취소 완료")
                    except Exception as e:
                        logger.warning(f"미체결 주문 취소 실패: {e}")
                    time.sleep(get_candle_sleep_time())
                    continue
                
                # 미체결 주문이 없을 때만 진입 시도
                usdt_to_use = balance * Decimal(str(POSITION_RATIO))
                if usdt_to_use <= 0:
                    logger.warning(f"잔고 부족: 사용 가능 USDT={balance:.4f}, 필요 금액={balance * Decimal(str(POSITION_RATIO)):.4f}")
                else:
                    # 수량 계산 및 거래소 스텝/최소수량 반영
                    raw_qty = usdt_to_use / current_price
                    qty_decimal = quantize_qty(raw_qty, step_size)
                    logger.info(f"[수량 계산] 사용 USDT={usdt_to_use:.4f}, 현재가={current_price:.2f}, 계산 수량={raw_qty:.8f}, 조정 수량={qty_decimal:.8f}, 최소수량={min_qty:.8f}")

                    if qty_decimal < min_qty:
                        logger.warning(f"[진입 불가] 계산된 수량 {qty_decimal:.8f} < 최소수량 {min_qty:.8f} → 진입 스킵")
                    else:
                        # 진입 조건: 2개 캔들 연속 확인으로 노이즈 필터링
                        long_condition = (
                            last_candle["ema20"] > last_candle["ema60"] and
                            prev_candle["ema20"] > prev_candle["ema60"] and
                            last_close > last_candle["ema20"] and
                            last_candle["rsi"] < 68
                        )
                        short_condition = (
                            last_candle["ema20"] < last_candle["ema60"] and
                            prev_candle["ema20"] < prev_candle["ema60"] and
                            last_close < last_candle["ema20"] and
                            last_candle["rsi"] > 32
                        )

                        if long_condition:
                            try:
                                # 시장가 진입
                                new_ord = client.new_order(symbol=SYMBOL, side="BUY", type="MARKET", quantity=float(qty_decimal))
                                logger.info(f"LONG 진입 주문 (2캔들 연속 확인): {new_ord}")
                                
                                # 1) 트레일링 스탑 (주요 손절)
                                try:
                                    trail = client.new_order(
                                        symbol=SYMBOL,
                                        side="SELL",
                                        type="TRAILING_STOP_MARKET",
                                        quantity=float(qty_decimal),
                                        callbackRate=float(TRAIL_RATE),
                                        reduceOnly=True
                                    )
                                    logger.info(f"[LONG] 트레일링 스탑 생성: {trail}")
                                except Exception as e:
                                    logger.warning(f"[LONG] 트레일링 스탑 생성 실패: {e}")
                                
                                # 2) 백업 익절 (TP: +5%)
                                tp_price = current_price * (1 + Decimal(str(BACKUP_TP)) / 100)
                                tp_price = quantize_price(tp_price, tick_size)  # 가격 정밀도 조정
                                try:
                                    take_profit = client.new_order(
                                        symbol=SYMBOL,
                                        side="SELL",
                                        type="TAKE_PROFIT_MARKET",
                                        quantity=float(qty_decimal),
                                        stopPrice=float(tp_price),
                                        reduceOnly=True
                                    )
                                    logger.info(f"[LONG] 백업 익절 생성 (TP={tp_price:.2f}): {take_profit}")
                                except Exception as e:
                                    logger.warning(f"[LONG] 백업 익절 생성 실패: {e}")
                                
                                # 3) 백업 손절 (SL: -5%)
                                sl_price = current_price * (1 - Decimal(str(abs(BACKUP_SL))) / 100)
                                sl_price = quantize_price(sl_price, tick_size)  # 가격 정밀도 조정
                                try:
                                    stop_loss = client.new_order(
                                        symbol=SYMBOL,
                                        side="SELL",
                                        type="STOP_MARKET",
                                        quantity=float(qty_decimal),
                                        stopPrice=float(sl_price),
                                        reduceOnly=True
                                    )
                                    logger.info(f"[LONG] 백업 손절 생성 (SL={sl_price:.2f}): {stop_loss}")
                                except Exception as e:
                                    logger.warning(f"[LONG] 백업 손절 생성 실패: {e}")
                            except Exception as e:
                                logger.error(f"LONG 진입 실패: {e}")

                        elif short_condition:
                            try:
                                new_ord = client.new_order(symbol=SYMBOL, side="SELL", type="MARKET", quantity=float(qty_decimal))
                                logger.info(f"SHORT 진입 주문 (2캔들 연속 확인): {new_ord}")
                                
                                # 1) 트레일링 스탑 (주요 손절)
                                try:
                                    trail = client.new_order(
                                        symbol=SYMBOL,
                                        side="BUY",
                                        type="TRAILING_STOP_MARKET",
                                        quantity=float(qty_decimal),
                                        callbackRate=float(TRAIL_RATE),
                                        reduceOnly=True
                                    )
                                    logger.info(f"[SHORT] 트레일링 스탑 생성: {trail}")
                                except Exception as e:
                                    logger.warning(f"[SHORT] 트레일링 스탑 생성 실패: {e}")
                                
                                # 2) 백업 익절 (TP: -5%, SHORT이므로 가격이 내려갈 때)
                                tp_price = current_price * (1 - Decimal(str(BACKUP_TP)) / 100)
                                tp_price = quantize_price(tp_price, tick_size)  # 가격 정밀도 조정
                                try:
                                    take_profit = client.new_order(
                                        symbol=SYMBOL,
                                        side="BUY",
                                        type="TAKE_PROFIT_MARKET",
                                        quantity=float(qty_decimal),
                                        stopPrice=float(tp_price),
                                        reduceOnly=True
                                    )
                                    logger.info(f"[SHORT] 백업 익절 생성 (TP={tp_price:.2f}): {take_profit}")
                                except Exception as e:
                                    logger.warning(f"[SHORT] 백업 익절 생성 실패: {e}")
                                
                                # 3) 백업 손절 (SL: +5%, SHORT이므로 가격이 올라갈 때)
                                sl_price = current_price * (1 + Decimal(str(abs(BACKUP_SL))) / 100)
                                sl_price = quantize_price(sl_price, tick_size)  # 가격 정밀도 조정
                                try:
                                    stop_loss = client.new_order(
                                        symbol=SYMBOL,
                                        side="BUY",
                                        type="STOP_MARKET",
                                        quantity=float(qty_decimal),
                                        stopPrice=float(sl_price),
                                        reduceOnly=True
                                    )
                                    logger.info(f"[SHORT] 백업 손절 생성 (SL={sl_price:.2f}): {stop_loss}")
                                except Exception as e:
                                    logger.warning(f"[SHORT] 백업 손절 생성 실패: {e}")
                            except Exception as e:
                                logger.error(f"SHORT 진입 실패: {e}")
                        else:
                            logger.info(
                                f"[진입 조건 미충족] "
                                f"EMA20={last_candle['ema20']:.2f}, EMA60={last_candle['ema60']:.2f}, "
                                f"가격={last_close:.2f}, RSI={last_candle['rsi']:.2f} | "
                                f"이전 캔들: EMA20={prev_candle['ema20']:.2f}, EMA60={prev_candle['ema60']:.2f}"
                            )

            # 루프 슬립: 다음 캔들 마감 시까지 동기화
            sleep_time = get_candle_sleep_time()
            logger.debug(f"다음 캔들 마감까지 {sleep_time:.1f}초 대기")
            time.sleep(sleep_time)

        except Exception as e:
            logger.exception(f"메인 루프 예외: {e}")
            time.sleep(get_candle_sleep_time())

# --- 봇 스레드 관리 (강건한 자동 재시작) -------------------------------------------------------
def bot_thread_wrapper():
    """봇 스레드 크래시 시 자동 재시작 로직"""
    retry_count = 0
    max_retries = 5
    retry_delay = 5  # 초
    
    while retry_count < max_retries:
        try:
            logger.info(f"[스레드 관리] 봇 시작 (재시작: {retry_count}/{max_retries})")
            run_bot()
        except KeyboardInterrupt:
            logger.info("[스레드 관리] 사용자 중단 신호")
            break
        except Exception as e:
            retry_count += 1
            logger.error(f"[스레드 관리] 봇 크래시: {e}")
            
            if retry_count < max_retries:
                logger.warning(f"[스레드 관리] {retry_delay}초 후 재시작... ({retry_count}/{max_retries})")
                time.sleep(retry_delay)
            else:
                logger.critical(f"[스레드 관리] 최대 재시작 횟수 도달 - 봇 종료")
                break
    
    logger.critical("[스레드 관리] 봇 스레드 종료")

# --- 실행부 -------------------------------------------------------------------------------
if __name__ == "__main__":
    # 봇 스레드: 강건한 자동 재시작 (daemon=False로 정상 종료 대기)
    bot_thread = Thread(target=bot_thread_wrapper, daemon=False)
    bot_thread.start()
    logger.info("[메인] 봇 스레드 시작")
    
    # Flask 서버: 메인 스레드에서 실행
    try:
        logger.info("[메인] Flask 서버 시작")
        run_server()
    except Exception as e:
        logger.error(f"[메인] Flask 서버 오류: {e}")
    finally:
        logger.info("[메인] 프로그램 종료")
        # 봇 스레드가 daemon=False이므로 자동으로 대기함
