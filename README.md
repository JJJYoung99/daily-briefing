# 매일 아침 피드

AI·IT 소식과 주식·코인 시장을 초보 눈높이로 정리한 **하루 3분 브리핑**을 매일 아침 7시(한국 시간)에 자동으로 만들어요.

- 📱 보는 곳: https://jjjyoung99.github.io/daily-briefing/
- 컴퓨터가 꺼져 있어도 돼요. GitHub 서버가 대신 실행해요.

## 어떻게 동작하나

1. 매일 아침 7시, GitHub Actions(`.github/workflows/daily.yml`)가 GitHub 서버에서 깨어나요.
2. `scripts/build.py`가 공개 RSS(긱뉴스, AI타임스, 한국경제, 연합뉴스, 블록미디어)와 무료 시세 API(Yahoo Finance, CoinGecko)에서 오늘 소식과 숫자를 모아요.
3. `ANTHROPIC_API_KEY`가 설정돼 있으면 Claude가 초보용 설명(핵심 한 줄, 시장이 움직인 이유, 오늘의 용어, AI 소식 5개)을 써요. 없으면 제목과 숫자만으로 된 기본 브리핑을 만들어요.
4. 결과(`docs/index.html`, `docs/archive/날짜.html`)를 저장소에 저장하면 GitHub Pages가 위 주소에 공개해요.

## 사용법

- **바로 다시 만들기:** 저장소의 Actions 탭 → "매일 아침 브리핑" → Run workflow
- **AI 요약 켜기:** Settings → Secrets and variables → Actions → New repository secret → 이름 `ANTHROPIC_API_KEY`, 값에 [Claude Console](https://console.anthropic.com)에서 만든 API 키
- **모델 바꾸기(선택):** 같은 화면 Variables 탭에서 `BRIEFING_MODEL` 변수 추가 (기본값 `claude-opus-5-5`, 더 싸게 하려면 `claude-haiku-5-5`)
- **시간 바꾸기:** `.github/workflows/daily.yml`의 `cron` 값 (UTC 기준, 한국 시간 −9시간)

공부용 요약이에요. 특정 종목이나 코인을 사고팔라는 추천이 아니에요.
