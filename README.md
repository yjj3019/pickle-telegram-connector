# Pickle Telegram Connector 🥒⚡

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Architecture](https://img.shields.io/badge/architecture-1--2s%20Low--Latency-brightgreen.svg)](ARCHITECTURE.md)

**Pickle Telegram Connector**는 AI 에이전트를 위한 **1~2초 저지연 텔레그램 봇 연동 및 고속 워처(Watcher) 엔진**입니다.

외부 서드파티 라이브러리 의존성 없이 **순수 Python 3 표준 라이브러리(Standard Library)**만으로 구현되어 라이선스 충돌 및 공급망 보안 위험이 전혀 없습니다.

---

## ⚡ 주요 특징

1. **30초 단위 안정적 감지 & 저지연 롱폴링 (Cadence Long-Polling)**
   - 무리한 서브세컨드 오버튜닝을 지양하고, 30초 롱폴링 주기를 기반으로 리소스 낭비 없이 메시지 인입 시 즉시 감지하여 안정적으로 회신합니다.
2. **감독 크론 + 워처 2계층 아키텍처 (Supervisor-Watcher Pattern)**
   - 리소스 소비를 최소화하면서도 24시간 무중단 가동을 보장하는 감시 체계를 지원합니다.
3. **엄격한 보안 및 접근 제어 (Zero-Trust Whitelisting)**
   - 허용된 관리자(`owner_ids`)의 1:1 DM만 수신·처리하며, 인가되지 않은 외부 사용자의 메시지는 조용히 무응답 폐기(`dropped.log`)합니다.
   - Nitro Enclave 및 환경변수 격리를 통해 토큰을 안전하게 보호합니다.
4. **운영 환경 즉시 배포 (Production Ready)**
   - Linux 환경을 위한 `systemd` 서비스 유닛 및 1클릭 설치 스크립트(`deploy.sh`)를 기본 제공합니다.
   - Podman / Docker 컨테이너 이미지 완벽 지원.
5. **실전 SLA 보장 (30초 감시 · 최대 1분 이내 회신) & 2분 전 사전 오버랩 인수인계**
   - 30초 단위 폴링으로 평시 30~45초 내에 회신을 완료하여 **최대 1분 이내 응답(SLA ≤ 60s)**을 견고하게 충족합니다.
   - 워처 임기 만료 2분 전(48분) 차기 워처를 사전 스폰하여 당직 교대 공백을 0초로 단축합니다.

---

## ⚠️ 토큰(크레딧) 사용량 주의 및 배포 권장 안내

> **중요 안내 (Token Consumption Notice)**:
> 
> - **피클 내부 런타임 상시 구동 시 토큰 급증 주의**:
>   피클(Pickle) 내부 환경에서 `subagent_spawn`을 이용해 상시 워처 루프를 24시간 가동할 경우, 30초~수 분 단위의 폴링 슬라이스마다 LLM 툴 호출 및 컨텍스트 추론이 지속적으로 발생하여 **일일 사용량 한도(토큰/크레딧)가 매우 빠르게 소진**될 수 있습니다. 특히 봇 간 연쇄 대화(Bot-to-Bot Loop)가 겹칠 경우 토큰 차감이 가속화됩니다.
>
> - **권장 아키텍처: RHEL / Linux 서버 systemd 데몬 배포 (토큰 0소모)**:
>   24시간 상시 무중단 감시와 즉시 응답을 안정적으로 운영하려면, 피클 내부 서브에이전트 상시 구동 대신 본 저장소에 포함된 `systemd` 서비스 유닛(`scripts/deploy.sh`)을 활용하여 **독립 Linux 서버에서 상시 데몬으로 구동**하는 방식을 강력히 권장합니다.
>   - 서버 데몬 방식으로 운영 시 **피클의 LLM 토큰 소모가 0(전혀 발생하지 않음)**입니다.
>   - 평시 롱폴링과 단순 응답은 서버 자체 프로세스가 초저지연(0.5초)으로 처리하고, 복잡한 비서 대행 작업이 필요할 때만 피클과 연동하므로 토큰을 극대화하여 절약할 수 있습니다.

---

## 📁 프로젝트 구조

```
pickle-telegram-connector/
├── LICENSE                    # MIT 라이선스
├── README.md                  # 프로젝트 안내서
├── ARCHITECTURE.md            # 1-2초 저지연 엔진 아키텍처 상세
├── pyproject.toml             # 패키징 메타데이터 (의존성 0개)
├── .gitignore
├── bin/
│   └── pickle-tg              # 실행 가능한 CLI 래퍼
├── pickle_tg/                 # 핵심 파이썬 패키지
│   ├── __init__.py
│   ├── client.py              # Telegram Bot API HTTP 클라이언트
│   ├── relay.py               # 큐 관리 (queue.jsonl, handled.txt, state.json)
│   ├── watcher.py             # 1~2초 저지연 롱폴링 워처 엔진
│   ├── supervisor.py          # 하트비트 감시 및 크론 관리자
│   ├── watchdog.py            # 타이핑 유지 및 지연 알림 감시견
│   └── cli.py                 # 통합 CLI 엔트리포인트
├── systemd/
│   └── pickle-telegram-connector.service  # RHEL systemd 서비스 파일
├── docker/
│   ├── Dockerfile             # 경량 알파인 컨테이너 이미지
│   └── docker-compose.yml
├── config/
│   └── local.json.template    # 로컬 설정 템플릿
└── scripts/
    ├── deploy.sh              # RHEL/Linux 1클릭 자동 배포 스크립트
    └── healthcheck.sh         # 헬스체크 스크립트
```

---

## 🚀 빠른 시작

### 1. 환경 설정 및 보안 토큰 등록

피클 텔레그램 커넥터는 토큰 유출을 원천 방지하기 위해 **2가지 보안 입력 체계**를 지원합니다:

#### A. 피클 에이전트 UI 전용: 단일 필드 보안 입력 카드 (`ask_user`)
- 채팅창에 평문 토큰을 입력하는 보안 위반을 방지하기 위해, 피클 에이전트는 `ask_user(kind='otp', service='Telegram Bot Token')` 보안 카드를 호출합니다.
- 사용자가 보안 팝업 카드에 입력한 토큰은 대화 로그나 프롬프트에 남지 않고 보안 인클레이브/로컬 설정으로 즉시 직결 저장됩니다.
- CLI에서 카드 호출 규격 확인:
  ```bash
  python3 -m pickle_tg.cli card-spec
  ```

#### B. 리눅스 / CLI 환경: 보안 마스킹 대화형 설정 (`pickle-tg setup`)
- 터미널에서 비밀번호 마스킹 방식으로 토큰을 안전하게 입력받고, 실시간 `getMe` 검증을 거쳐 `0600` 권한의 `local.json`을 자동 생성합니다:
  ```bash
  python3 -m pickle_tg.cli setup
  ```

#### C. 파일/환경변수 직접 지정
`config/local.json.template` 파일을 복사하여 `config/local.json`을 생성하고 봇 토큰과 허용 ID를 입력합니다:

```json
{
  "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
  "bot_id": 123456789,
  "bot_username": "YourAgentBot",
  "owner_ids": [123456789],
  "group_ids": []
}
```

*또는 환경변수로 지정할 수 있습니다:*
```bash
export TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
export TG_OWNER_IDS="123456789"
```

### 2. CLI 기본 동작 검증

```bash
# 봇 정보 확인
python3 -m pickle_tg.cli get-me

# 사용자 프로필 확인
python3 -m pickle_tg.cli get-chat --chat-id 123456789

# 메시지 발송 테스트
python3 -m pickle_tg.cli send-message --chat-id 123456789 --text "안녕하세요! 텔레그램 연동 정상 가동 중입니다. ✨"
```

### 3. 실시간 워처(Watcher) 가동

```bash
# 단일 슬라이스 감시 (최대 600초 동안 롱폴링 대기 후 메시지 수신 즉시 반환)
python3 -m pickle_tg.cli watch --slice 600

# 상시 데몬 모드 실행 (24시간 무중단 1~2초 실시간 응답)
python3 -m pickle_tg.cli daemon
```

---

## 🛠️ RHEL / Linux 서버 상시 배포 (systemd)

제공된 `scripts/deploy.sh`를 실행하면 `/opt/pickle-telegram-connector` 경로에 자동 설치되고 `systemd` 데몬으로 등록됩니다:

```bash
git clone https://github.com/yjj3019/pickle-telegram-connector.git
cd pickle-telegram-connector
sudo ./scripts/deploy.sh
```

수동 서비스 제어:
```bash
sudo systemctl status pickle-telegram-connector
sudo journalctl -u pickle-telegram-connector -f
```

---

## 🔒 보안 및 라이선스 (Clean-Room Design)

- **License**: MIT License (Copyright (c) 2026 yjj3019)
- **Zero-Dependency**: 외부 종속성 없이 순수 표준 라이브러리로만 작성되어 라이선스 분쟁 우려 없이 자유롭게 사용 및 수정이 가능합니다.
