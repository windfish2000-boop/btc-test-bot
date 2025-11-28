# 바이낸스 테스트넷 선물 트레이딩 봇
import ccxt, pandas as pd, time, os
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "테스트넷 봇 살아있어요! " + time.strftime('%H:%M')

def run_server():
    app.run(host='0.0.0.0', port=5000)

API_KEY = os.environ.get('API_KEY', '')
API_SECRET = os.environ.get('API_SECRET', '')

def run_bot():
    if not API_KEY or not API_SECRET:
        print("API_KEY와 API_SECRET 환경변수를 설정해주세요!")
        return
    
    ex = ccxt.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
        'urls': {'api': {'fapi': 'https://testnet.binancefuture.com/fapi/v1'}},
        'options': {'defaultType': 'future'}
    })

    try:
        ex.fapiPrivate_post_margintype({'symbol':'BTCUSDT','marginType':'ISOLATED'})
    except Exception as e:
        print("마진타입 설정:", e)
    
    try:
        ex.fapiPrivate_post_leverage({'symbol':'BTCUSDT','leverage':1})
    except Exception as e:
        print("레버리지 설정:", e)

    print("테스트넷 봇 가동 시작! 가상 10,000 USDT로 연습 중")

    while True:
        try:
            d = pd.DataFrame(ex.fetch_ohlcv('BTCUSDT','15m',limit=200),
                             columns=['t','o','h','l','c','v'])
            d['e20'] = d['c'].ewm(span=20,adjust=False).mean()
            d['e60'] = d['c'].ewm(span=60,adjust=False).mean()
            delta = d['c'].diff()
            g = delta.clip(lower=0).rolling(14).mean()
            l = (-delta.clip(upper=0)).rolling(14).mean()
            d['rsi'] = 100-100/(1+g/l)
            c = d.iloc[-2]
            amt = float(ex.fapiPrivate_v2_get_positionrisk({'symbol':'BTCUSDT'})[0]['positionAmt'])

            if amt == 0:
                money = float(ex.fetch_balance()['USDT']['free'])
                qty = round(money * 0.1 / c['c'], 3)
                if qty >= 0.001:
                    if c['e20']>c['e60'] and c['c']>c['e20'] and c['rsi']<68:
                        ex.create_market_buy_order('BTCUSDT', qty)
                        ex.create_order('BTCUSDT','TRAILING_STOP_MARKET','sell',qty,params={'callbackRate':1.5})
                        print(time.strftime('%H:%M'),"테스트 LONG 진입")
                    elif c['e20']<c['e60'] and c['c']<c['e20'] and c['rsi']>32:
                        ex.create_market_sell_order('BTCUSDT', qty)
                        ex.create_order('BTCUSDT','TRAILING_STOP_MARKET','buy',qty,params={'callbackRate':1.5})
                        print(time.strftime('%H:%M'),"테스트 SHORT 진입")
            time.sleep(30)
        except Exception as e:
            print("에러",e)
            time.sleep(30)

if __name__ == '__main__':
    Thread(target=run_bot, daemon=True).start()
    run_server()
