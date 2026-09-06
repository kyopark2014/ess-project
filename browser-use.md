# Browser Use

Agent가 Chrome/Chromium을 직접 제어하기 위한 CLI이자 Agent Skill입니다. 웹 페이지 탐색, 클릭/입력, 스크린샷, 데이터 추출, 로그인된 세션 활용, JS 렌더링·봇 보호 페이지 대응에 사용합니다.

**상호작용·로그인 세션·JS 렌더링·봇 보호**가 필요할 때만 Browser Use를 씁니다.

---

## 제공처

| 항목 | 내용 |
|------|------|
| 제품 | [Browser Use](https://browser-use.com) |
| 오픈소스 | [github.com/browser-use/browser-use](https://github.com/browser-use/browser-use) |
| CLI/문서 | [docs.browser-use.com — Browser Use CLI](https://docs.browser-use.com/open-source/browser-use-cli) |
| 클라우드 | [cloud.browser-use.com](https://cloud.browser-use.com) (격리된 원격 Chrome, CAPTCHA/프록시 등) |

Browser Use 팀이 배포하는 Python 패키지 `browser-use`이며, 에이전트용 Skill(`SKILL.md`)과 함께 설치됩니다.

---

## 이 환경에 설치된 상태 (2026-09-06)

| 항목 | 값 |
|------|------|
| 설치 방식 | `uv tool install` (전역 CLI) |
| 패키지 버전 | **browser-use 0.13.10** |
| CLI 경로 | `~/.local/bin/browser-use` |
| 별칭 | `bu`, `browser`, `browseruse` |
| Python | 3.12.14 (`uv`가 관리하는 tool env) |
| Skill 원본 | `application/skills/browser-use/SKILL.md` |
| Skill 배포 위치 | `~/.cursor/skills/browser-use/`, `~/.claude/skills/browser-use/`, `~/.agents/skills/browser-use/` |

버전 확인:

```bash
browser-use --version
uv tool list | grep browser-use
```

---

## 설치 방법

### 이번에 수행한 설치

```bash
# 1) 최신 CLI 설치 (GitHub main, Python 3.12)
uv tool install --python 3.12 --upgrade --force \
  'browser-use @ git+https://github.com/browser-use/browser-use.git'

# 2) Agent Skill 설치 (Cursor / Claude / agents 등)
browser-use skill install --no-install --target cursor
browser-use skill install --no-install --target claude
browser-use skill install --no-install --target agents

# 또는 agent-skills 레포에만 반영
browser-use skill install --no-install \
  --path /Users/ksdyb/Documents/src/agent-skills/application/skills/browser-use
```

`--no-install`은 CLI를 다시 받지 않고 Skill 파일만 쓰는 옵션입니다. 전체 재설치까지 하려면 `browser-use skill install`(기본)을 쓰면 `uv tool install browser-use`도 같이 돌립니다.

### PyPI만으로 설치 (문서 기본)

```bash
uv tool install --python 3.12 browser-use
# 일회성
uvx browser-use --help
```

### 업데이트

```bash
browser-use --update -y
# 또는
uv tool install --python 3.12 --upgrade --force browser-use
browser-use skill install --no-install --target all
```

### PATH

`uv tool`은 보통 `~/.local/bin`에 링크를 만듭니다. 셸에 없으면:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

---

## 동작 개념

1. **Python heredoc으로 명령을 넘김** — 헬퍼 함수가 미리 import된 상태로 실행됩니다.
2. **백그라운드 데몬**이 브라우저 CDP 연결을 유지합니다. 호출마다 Chrome을 새로 띄우지 않습니다.
3. **기본은 로컬 Chrome** — 이미 열려 있는 탭·쿠키·확장·로그인 상태를 그대로 씁니다.
4. **대안** — Browser Use Cloud 원격 브라우저, 또는 `BU_CDP_URL` / `BU_CDP_WS`로 외부 CDP 엔드포인트.

첫 탐색은 `goto_url`이 아니라 **`new_tab(url)`** 입니다. 데몬이 탭을 유지하므로 매 스크립트마다 `new_tab()`을 반복하지 마세요.

---

## 기본 사용법

### 최소 예제

```bash
browser-use <<'PY'
ensure_real_tab()
print(page_info())
PY
```

```bash
browser-use <<'PY'
new_tab("https://example.com")
wait_for_load()
print(page_info())
PY
```

PowerShell에서는 heredoc 대신 here-string 파이프를 씁니다:

```powershell
@'
new_tab("https://example.com")
print(page_info())
'@ | browser-use
```

### 페이지 작업 흐름 (권장)

1. `ensure_real_tab()` / `new_tab(url)` / `wait_for_load()`
2. 요소 찾기: Accessibility tree (`cdp("Accessibility.getFullAXTree")`) 우선, 스크린샷은 레이아웃·이미지가 필요할 때
3. 클릭: AX 노드 → `DOM.getBoxModel`로 중심 좌표 → `click_at_xy(x, y)`
4. 검증: `js(...)` 또는 `page_info()`
5. AX에 없는 위젯만 `js(...)`로 HTML/DOM 폴백
6. 로그인 벽(비밀번호·MFA·동의)은 멈추고 사용자에게 확인. Chrome에 이미 된 SSO만 자동 사용

좌표 클릭이 기본입니다. CDP 마우스 이벤트는 iframe / shadow DOM / cross-origin에도 compositor 수준으로 통과합니다.

### 탭 관리

```bash
browser-use <<'PY'
print(current_tab())
print(list_tabs())
# 같은 URL 탭이 있으면 switch_tab()으로 재사용
# activate_tab()은 사용자가 명시하거나, 숨은 탭에서 렌더가 멈출 때만
PY
```

- 작업당 탭 하나 유지
- `new_tab` / `switch_tab`은 말 표시(horse marker)만 옮기고 Chrome의 보이는 탭은 바꾸지 않음
- 마커를 끄려면 데몬 시작 전 `BH_TAB_MARKER=0`

### 로컬 Chrome 연결 문제

```bash
browser-use --doctor    # 또는 browser-use doctor
```

- Chrome이 꺼져 있으면 자동으로 띄운 뒤 재시도
- Remote debugging이 꺼져 있으면 `chrome://inspect/#remote-debugging`을 염
- macOS에서 “Allow remote debugging?” 팝업이 뜨면, **원래 명령을 기다린 채** 다른 터미널에서:

```bash
browser-use mac-approve
# 이름 있는 데몬이면: BU_NAME=r7k2 browser-use mac-approve
```

Accessibility 권한이 필요하면(Terminal / iTerm / Cursor 등) 시스템 설정에서 허용한 뒤 `mac-approve`를 한 번 더 실행합니다.

### 외부 CDP

```bash
BU_CDP_URL=http://127.0.0.1:9222 browser-use <<'PY'
print(page_info())
PY
```

`BU_CDP_URL`은 HTTP DevTools 엔드포인트이고, 데몬이 WebSocket으로 resolve합니다. WebSocket을 직접 줄 때는 `BU_CDP_WS`를 씁니다.

---

## Cloud 브라우저

병렬 작업, 헤드리스 서버, CAPTCHA·차단이 예상될 때 로컬 Chrome 대신 클라우드 인스턴스를 씁니다.

```bash
# 인증 (한 번)
browser-use auth login
# 또는
printf '%s' "$BROWSER_USE_API_KEY" | browser-use auth login --api-key-stdin
browser-use auth status

# 이름 있는 원격 데몬 시작
browser-use <<'PY'
start_remote_daemon("work")
PY

BU_NAME=work browser-use <<'PY'
new_tab("https://example.com")
print(page_info())
PY

# 작업 후 종료 (과금 방지 — 사용자에게 닫을지 확인)
BU_NAME=work browser-use <<'PY'
stop_remote_daemon("work")
PY
```

원격 데몬을 띄운 뒤에는 **같은 `BU_NAME`만** 사용하세요. 기본(로컬) 데몬과 섞지 않습니다.

---

## 자주 쓰는 CLI 명령

| 명령 | 설명 |
|------|------|
| `browser-use <<'PY' ... PY` | Python으로 브라우저 제어 |
| `browser-use --doctor` | 설치·데몬·브라우저 진단 |
| `browser-use mac-approve` | macOS remote debugging 승인 보조 |
| `browser-use auth login / status / logout` | Cloud 인증 |
| `browser-use skill show` | Skill 전문 출력 |
| `browser-use skill install` | Skill을 에이전트 디렉터리에 설치 |
| `browser-use recordings enable\|disable` | 로컬 액션 기록 on/off |
| `browser-use recordings --latest` | 최근 녹화 디렉터리 |
| `browser-use video init\|review\|export` | 녹화 → 영상 |
| `browser-use --update -y` | 최신으로 업데이트 |
| `browser-use --reload` | 데몬 중지(다음 호출에서 새 코드 반영) |
| `browser-use telemetry status` | 익명 텔레메트리 상태 |

---

## 녹화

기본 설치는 녹화를 켜지 않습니다.

```bash
browser-use recordings enable
browser-use <<'PY'
path = start_recording("demo", title="Example flow")
new_tab("https://example.com")
# ... 작업 ...
stop_recording()
print(path)
PY
```

작업 중 `BH_RECORD=1` / `BH_RECORD=0`으로 한 프로세스만 덮어쓸 수 있습니다.

---

## 환경 변수 (요약)

| 변수 | 역할 |
|------|------|
| `BU_NAME` | 이름 있는 데몬(특히 Cloud) 선택 |
| `BU_CDP_URL` / `BU_CDP_WS` | 외부 CDP 연결 |
| `BH_TAB_MARKER=0` | 탭 제목 말 표시 끄기 |
| `BH_RECORD=0\|1` | 녹화 일시 강제 |
| `BH_DOMAIN_SKILLS=1` | 사이트별 domain skill 사용 |
| `BH_OPEN_LIVE_URL=0` | Cloud live-view URL 출력/오픈 억제 |
| `BH_REQUIRE_EXISTING_DAEMON=1` | 기존 이름 데몬만 재사용, 자동 시작 금지 |
| `BROWSER_USE_API_KEY` | Cloud API 키 (`auth login --api-key-stdin`) |
| `BH_AGENT_WORKSPACE` | `agent_helpers.py`, domain-skills 위치 |

---

## Agent Skill

에이전트가 “언제·어떻게 CLI를 호출할지” 읽는 문서가 Skill입니다.

- 레포: `agent-skills/application/skills/browser-use/SKILL.md`
- 설치본: `~/.cursor/skills/browser-use/SKILL.md` 등
- 내용 확인: `browser-use skill show`

세부 메커니즘(쿠키, iframe, 다운로드, shadow DOM 등)은 [interaction-skills](https://github.com/browser-use/browser-harness/tree/main/interaction-skills)를 참고하고, 연결/설치 문제는 [install.md](https://github.com/browser-use/browser-harness/blob/main/install.md)를 따릅니다.

작업 전용 헬퍼는 `$BH_AGENT_WORKSPACE/agent_helpers.py`에 두고, 코어 헬퍼를 늘리지 않는 것이 권장입니다.

---

## 빠른 체크리스트

1. `which browser-use` → `~/.local/bin/browser-use`
2. `browser-use --doctor` → Chrome / 데몬 / CDP 상태 확인
3. macOS 팝업 시 `browser-use mac-approve`
4. `browser-use <<'PY' ...` 로 `new_tab` → `wait_for_load` → AX tree → `click_at_xy`
5. Cloud 사용 시 `auth login` → `start_remote_daemon` → `BU_NAME=...` → 끝나면 `stop_remote_daemon`
6. Skill/CLI 갱신: `browser-use --update -y` 후 `browser-use skill install --no-install --target all`
