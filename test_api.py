#!/usr/bin/env python3
"""Binance 테스트넷 API 연결 테스트"""

import os
from binance.um_futures import UMFutures
import json

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
TESTNET_BASE_URL = "https://testnet.binance.com/fapi"

print("=" * 60)
print("🔍 Binance 테스트넷 API 연결 테스트")
print("=" * 60)

# 1. 환경변수 확인
print("\n1️⃣ 환경변수 확인:")
print(f"   API_KEY: {'✅ 설정됨' if API_KEY else '❌ 미설정'}")
print(f"   API_SECRET: {'✅ 설정됨' if API_SECRET else '❌ 미설정'}")

if not API_KEY or not API_SECRET:
    print("\n❌ API 키가 설정되지 않았습니다!")
    exit(1)

# 2. 클라이언트 생성
print("\n2️⃣ 클라이언트 생성:")
try:
    client = UMFutures(key=API_KEY, secret=API_SECRET, base_url=TESTNET_BASE_URL)
    print("   ✅ 클라이언트 생성 성공")
except Exception as e:
    print(f"   ❌ 클라이언트 생성 실패: {e}")
    exit(1)

# 3. 서버 시간 확인
print("\n3️⃣ 서버 연결 테스트:")
try:
    server_time = client.time()
    print(f"   ✅ 서버 시간: {server_time}")
except Exception as e:
    print(f"   ❌ 서버 연결 실패: {e}")
    exit(1)

# 4. 계정 정보 확인
print("\n4️⃣ 계정 정보:")
try:
    account = client.account()
    print(f"   ✅ 계정 조회 성공")
    print(f"   💰 잔액: {account.get('totalWalletBalance', 'N/A')}")
    print(f"   🔐 포지션 수: {len(account.get('positions', []))}")
except Exception as e:
    print(f"   ❌ 계정 조회 실패: {e}")

# 5. 캔들 데이터 확인
print("\n5️⃣ 캔들 데이터 (BTCUSDT, 15m):")
try:
    klines = client.klines("BTCUSDT", "15m", limit=5)
    print(f"   ✅ 데이터 받음: {len(klines)}개 캔들")
    if klines:
        print(f"   최신 종가: {klines[-1][4]}")
except Exception as e:
    print(f"   ❌ 캔들 데이터 조회 실패: {e}")

# 6. 심볼 정보 확인
print("\n6️⃣ 심볼 정보 (BTCUSDT):")
try:
    info = client.exchange_info()
    if isinstance(info, str):
        info = json.loads(info)
    
    for s in info.get("symbols", []):
        if s.get("symbol") == "BTCUSDT":
            print(f"   ✅ 심볼 찾음")
            print(f"   상태: {s.get('status', 'N/A')}")
            print(f"   마진 가능: {s.get('marginTrading', 'N/A')}")
            break
except Exception as e:
    print(f"   ❌ 심볼 정보 조회 실패: {e}")

print("\n" + "=" * 60)
print("✅ 테스트 완료!")
print("=" * 60)
