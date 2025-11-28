# 바이낸스 테스트넷 선물 트레이딩 봇
import ccxt, pandas as pd, time, os
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

def run_bot():
    if not API_KEY or not API_SECRET:
        print("API_KEY와 API_SECRET 환경변수를 설정해주세요!")
        return
    
    ex = ccxt.binanceusdm({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future',
        },
        'urls': {
            'api': {
                'public': 'https://testnet.binancefuture.com/fapi/v1',
                'private': 'https://testnet.binancefuture.com/fapi/v1',
                'fapiPublic': 'https://testnet.binancefuture.com/fapi/v1',
                'fapiPrivate': 'https://testnet.binancefuture.com/fapi/v1',
                'fapiPublicV2': 'https://testnet.binancefuture.com/fapi/v2',
                'fapiPrivateV2': 'https://testnet.binancefuture.com/fapi/v2',
            }
        }
    })

    try:
        ex.set_margin_mode('isolated', 'BTC/USDT:USDT')
        print("마진타입 ISOLATED 설정 완료")
    except Exception as e:
        print("마진타입 설정:", e)
    
    try:
        ex.set_leverage(1, 'BTC/USDT:USDT')
        print("레버리지 1x 설정 완료")
    except Exception as e:
        print("레버리지 설정:", e)

    print("테스트넷 봇 가동 시작! 가상 10,000 USDT로 연습 중")

    while True:
        try:
            d = pd.DataFrame(ex.fetch_ohlcv('BTC/USDT:USDT','15m',limit=200),
                             columns=['t','o','h','l','c','v'])
            d['e20'] = d['c'].ewm(span=20,adjust=False).mean()
            d['e60'] = d['c'].ewm(span=60,adjust=False).mean()
            delta = d['c'].diff()
            g = delta.clip(lower=0).rolling(14).mean()
            l = (-delta.clip(upper=0)).rolling(14).mean()
            d['rsi'] = 100-100/(1+g/l)
            c = d.iloc[-2]
            
            positions = ex.fetch_positions(['BTC/USDT:USDT'])
            amt = 0
            for pos in positions:
                if pos['symbol'] == 'BTC/USDT:USDT':
                    amt = float(pos['contracts'] or 0)
                    break

            if amt == 0:
                balance = ex.fetch_balance()
                money = float(balance['USDT']['free'])
                qty = round(money * 0.1 / c['c'], 3)
                if qty >= 0.001:
                    if c['e20']>c['e60'] and c['c']>c['e20'] and c['rsi']<68:
                        ex.create_market_buy_order('BTC/USDT:USDT', qty)
                        ex.create_order('BTC/USDT:USDT','TRAILING_STOP_MARKET','sell',qty,params={'callbackRate':1.5})
                        print(time.strftime('%H:%M'),"테스트 LONG 진입")
                    elif c['e20']<c['e60'] and c['c']<c['e20'] and c['rsi']>32:
                        ex.create_market_sell_order('BTC/USDT:USDT', qty)
                        ex.create_order('BTC/USDT:USDT','TRAILING_STOP_MARKET','buy',qty,params={'callbackRate':1.5})
                        print(time.strftime('%H:%M'),"테스트 SHORT 진입")
            time.sleep(30)
        except Exception as e:
            print("에러:",e)
            time.sleep(30)

if __name__ == '__main__':
    Thread(target=run_bot, daemon=True).start()
    run_server()
