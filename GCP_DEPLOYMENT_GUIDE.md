# 🚀 구글 클라우드(GCP) 배포 가이드

## 📋 구글 클라우드 Compute Engine에서 실행하기

### 1️⃣ **GCP 프로젝트 생성 및 VM 인스턴스 생성**

```bash
# GCP Console에서:
1. Compute Engine > VM 인스턴스 > 인스턴스 만들기
2. 설정:
   - 이름: trading-bot
   - 머신 유형: e2-micro (또는 f1-micro) - 무료 트라이얼 사용 가능
   - 이미지: Ubuntu 20.04 LTS
   - 방화벽: HTTP, HTTPS 허용
   - 시작 스크립트 (아래 참조)
```

### 2️⃣ **시작 스크립트 설정**

VM 생성 시 "고급 옵션 > 관리 > 시작 스크립트" 에 다음 내용 추가:

```bash
#!/bin/bash

# 시스템 업데이트
apt-get update
apt-get install -y python3 python3-pip git

# 작업 디렉토리
mkdir -p /opt/trading-bot
cd /opt/trading-bot

# 코드 다운로드 (Git 또는 수동 업로드)
git clone <YOUR_GITHUB_REPO> .

# 필요 패키지 설치
pip3 install -r requirements.txt

# 환경변수 설정 (아래 참조)
export API_KEY="your_binance_api_key"
export API_SECRET="your_binance_api_secret"
export TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
export TELEGRAM_CHAT_ID="your_telegram_chat_id"

# 봇 실행 (백그라운드)
nohup python3 main.py > /var/log/trading_bot.log 2>&1 &
```

### 3️⃣ **환경변수 설정 (GCP에서)**

**방법 A: SSH 접속 후 설정**
```bash
# VM에 SSH 접속
gcloud compute ssh trading-bot --zone=us-central1-a

# 환경변수 설정
export API_KEY="your_key"
export API_SECRET="your_secret"
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# 봇 시작
python3 main.py
```

**방법 B: systemd 서비스로 등록 (권장)**

`/etc/systemd/system/trading-bot.service` 파일 생성:

```ini
[Unit]
Description=Trading Bot Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/trading-bot
Environment="API_KEY=your_key"
Environment="API_SECRET=your_secret"
Environment="TELEGRAM_BOT_TOKEN=your_token"
Environment="TELEGRAM_CHAT_ID=your_chat_id"
ExecStart=/usr/bin/python3 /opt/trading-bot/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

그 후:
```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-bot
sudo systemctl start trading-bot
sudo systemctl status trading-bot
```

### 4️⃣ **로그 확인**

```bash
# 실시간 로그 보기
tail -f trading_bot.log

# 또는 systemd 로그
sudo journalctl -u trading-bot -f
```

### 5️⃣ **웹 모니터링 (선택사항)**

봇이 `http://YOUR_VM_IP:8080` 에서 헬스체크 엔드포인트 제공합니다.

```bash
# VM 공개 IP 확인
gcloud compute instances list
```

---

## 💰 **GCP 비용 (무료 트라이얼 사용 시)**

- **프리 트라이얼**: $300 (90일)
- **e2-micro**: 월 약 $7-10 (프리 티어 포함 시 일부 무료)
- **스토리지**: 로그는 VM 로컬 저장

---

## ⚠️ **주의사항**

1. **API 키 보안**: 환경변수에 저장, Git에 커밋 금지
2. **방화벽**: 필요한 포트만 열기 (8080 필수)
3. **자동 종료**: 비용 절감을 위해 미사용 시 VM 중지
4. **백업**: 거래 로그는 주기적으로 백업

---

## 🔧 **문제 해결**

**봇이 안 켜지는 경우:**
```bash
# 1. 파이썬 설치 확인
python3 --version

# 2. 패키지 설치 확인
pip3 list | grep -E "binance|pandas|flask|telegram"

# 3. API 키 확인
echo $API_KEY
echo $API_SECRET

# 4. 로그 확인
cat trading_bot.log
```

---

이 가이드를 따르면 구글 클라우드에서 24/7 안정적으로 봇을 운영할 수 있습니다! 🚀
