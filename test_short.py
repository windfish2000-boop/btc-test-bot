# -*- coding: utf-8 -*-
import os
from decimal import Decimal
from binance.um_futures import UMFutures

# 환경변수에서 API 키 가져오기
API_KEY = os.environ.get("API_KEY", "")
API_SECRET = os.environ.get("API_SECRET", "")

print(f"✅ API 키 확인: {'있음' if API_KEY else '없음'}")
print(f"✅ API 시크릿 확인: {'있음' if API_SECRET else '없음'}")

if not API_KEY or not API_SECRET:
    print("❌ API 키가 없습니다!")
    exit(1)

# 테스트넷 클라이언트 생성
client = UMFutures(
    key=API_KEY,
    secret=API_SECRET,
    base_url="https://testnet.binance.com/fapi"
)

print("\n🔄 테스트넷 연결 시도...")

try:
    # 1. 계정 정보 확인
    account = client.account()
    print("✅ 계정 연결 성공!")
    
    # USDT 잔고 확인
    for asset in account.get("assets", []):
        if asset.get("asset") == "USDT":
            balance = float(asset.get("availableBalance", 0))
            print(f"💰 USDT 잔고: {balance}")
    
    # 2. SHORT 테스트 거래
    print("\n🔄 SHORT 테스트 거래 시작...")
    print("심볼: BTCUSDT")
    print("수량: 0.001 (가장 작은 단위)")
    
    try:
        order = client.new_order(
            symbol="BTCUSDT",
            side="SELL",
            type="MARKET",
            quantity=0.001
        )
        print(f"\n✅ SHORT 진입 성공!")
        print(f"주문 ID: {order.get('orderId')}")
        print(f"상태: {order.get('status')}")
        print(f"수량: {order.get('executedQty')}")
        print(f"체결가: {order.get('avgPrice')}")
        
    except Exception as e:
        print(f"❌ SHORT 거래 실패: {e}")
        
except Exception as e:
    print(f"❌ 테스트넷 연결 실패: {e}")
