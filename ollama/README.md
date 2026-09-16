# 올라마(Ollama) 효율 사용 가이드

로컬에서 LLM을 돌릴 때 체감 속도와 품질의 90%는 **모델 선택 · GPU 적재 여부 · 컨텍스트 설정** 세 가지에서 갈린다. 나머지는 취향 문제다.

## 1. 모델은 VRAM에 맞춰 고른다

Q4_K_M 양자화 기준 가중치 용량은 대략 **파라미터 수(B) × 0.6~0.7GB**다. 8B 모델이면 약 5GB. 여기에 KV 캐시와 여유분이 더 붙으므로, VRAM의 80% 안에 들어오는 크기를 고른다.

| VRAM | 무난한 크기 | 비고 |
|---|---|---|
| 8GB | 3B~8B (Q4) | 컨텍스트 8k 이하 |
| 12~16GB | 8B~14B (Q4_K_M) | 일상 작업 기준 최적 구간 |
| 24GB | 14B~32B (Q4) | 32B는 컨텍스트를 아껴야 함 |

양자화는 **Q4_K_M을 기본값**으로 두면 된다. Q8은 용량이 2배인데 체감 품질 차이는 작고, Q3 이하는 눈에 띄게 무너진다. 같은 VRAM이라면 "큰 모델의 Q3"보다 "작은 모델의 Q4~Q5"가 대체로 낫다.

작업별로 모델을 나누는 편이 크기를 키우는 것보다 효율적이다. 분류·추출·포맷 변환 같은 정형 작업은 3B급으로도 충분하고, 코드는 코딩 특화 모델(qwen2.5-coder 계열), 일반 요약·대화는 8B급 범용 모델이 무난하다.

## 2. GPU에 100% 올라갔는지부터 확인한다

로컬 LLM이 느린 경우의 대부분은 모델 일부가 CPU로 밀려난 것이다. 일부만 CPU로 가도 속도는 5~10배 떨어진다.

```bash
ollama ps
# NAME          SIZE     PROCESSOR         UNTIL
# llama3.1:8b   6.1 GB   100% GPU          4 minutes from now
```

`PROCESSOR`에 `20%/80% CPU/GPU` 같은 값이 보이면 모델을 한 단계 줄이거나, 컨텍스트를 줄이거나, 다른 모델을 언로드해야 한다.

실제 처리 속도는 `--verbose`로 확인한다.

```bash
ollama run llama3.1:8b --verbose "한 문장으로 자기소개해줘"
# eval rate: 48.2 tokens/s   ← 이 값이 기준선
```

## 3. 컨텍스트와 KV 캐시 조절

기본 컨텍스트는 보수적으로 잡혀 있어서(과거 버전 기준 4096) 긴 문서를 넣으면 앞부분이 조용히 잘린다. 반대로 무작정 128k로 열면 KV 캐시가 VRAM을 다 먹고 CPU로 밀려난다.

8B급 GQA 모델 기준 KV 캐시는 f16에서 **토큰당 약 128KB**다. 4k면 0.5GB, 32k면 4GB. 즉 컨텍스트를 8배 늘리면 모델 하나를 더 올리는 것과 비슷한 비용이 든다.

```bash
# 서버 전역 기본값
OLLAMA_CONTEXT_LENGTH=8192 ollama serve

# KV 캐시를 8비트로 (플래시 어텐션 필요) → 캐시 용량 절반
OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve
```

대화 중 임시 변경:

```
>>> /set parameter num_ctx 16384
```

원칙은 단순하다. **실제로 넣는 입력보다 조금 큰 값**으로 잡는다. 회의록 요약에 32k가 필요하면 32k를, 커밋 메시지 생성이면 4k를 쓴다. 하나의 전역값으로 모든 작업을 덮으려 하면 손해다.

## 4. 로딩 비용 줄이기

모델 로드는 수 초~수십 초가 걸린다. 자주 쓰는 모델은 메모리에 붙잡아 둔다.

```bash
# 상시 상주 (워크스테이션)
OLLAMA_KEEP_ALIVE=-1 ollama serve

# 요청 단위로 지정
curl http://localhost:11434/api/chat -d '{
  "model": "llama3.1:8b",
  "messages": [{"role":"user","content":"안녕"}],
  "keep_alive": "30m"
}'

# 즉시 내리기 (노트북 배터리 절약)
curl http://localhost:11434/api/generate -d '{"model":"llama3.1:8b","keep_alive":0}'
```

`OLLAMA_MAX_LOADED_MODELS`로 동시에 올릴 모델 수를, `OLLAMA_NUM_PARALLEL`로 동시 처리 슬롯 수를 정한다. 주의할 점은 **병렬 슬롯이 컨텍스트를 나눠 쓴다**는 것이다. num_ctx 32k에 슬롯 4개면 요청당 실질 8k다.

프롬프트 앞부분(시스템 프롬프트 등)이 동일하면 프리픽스 캐시가 재사용되어 첫 토큰이 빨라진다. 시스템 프롬프트를 매번 바꾸거나 타임스탬프를 앞에 붙이는 습관은 이 이점을 버리는 것이다.

## 5. 설정은 Modelfile로 고정한다

매 호출마다 옵션을 반복하는 대신 용도별 모델을 만들어 둔다.

```dockerfile
# Modelfile
FROM llama3.1:8b
PARAMETER num_ctx 16384
PARAMETER temperature 0.2
PARAMETER num_predict 800
SYSTEM """너는 컨설팅 스튜디오의 운영 담당자다.
회의록을 받아 결정사항, 담당자, 기한만 뽑아낸다. 추측하지 않는다."""
```

```bash
ollama create meeting -f Modelfile
ollama run meeting < 회의록.txt
ollama show meeting --modelfile   # 기존 모델 설정 확인·복제용
```

요약·추출처럼 정답이 정해진 작업은 `temperature 0`~`0.2`가 기본이다. 기본값(0.8)을 그대로 쓰면 없는 내용을 지어낸다.

## 6. 사용 예시

### 파이프라인으로 쓰기

```bash
# 커밋 메시지 초안
git diff --staged | ollama run qwen2.5-coder:7b \
  "이 diff에 대한 한국어 커밋 메시지를 한 줄로. 설명 없이 메시지만."

# 로그에서 에러 패턴만 뽑기
tail -500 app.log | ollama run llama3.1:8b "반복되는 에러 유형 3개를 빈도순으로"
```

### 구조화 출력 (JSON 스키마 강제)

프롬프트로 "JSON만 출력해"라고 부탁하지 말고 스키마를 걸면 파싱 실패가 사라진다.

```bash
curl http://localhost:11434/api/chat -d '{
  "model": "llama3.1:8b",
  "stream": false,
  "options": {"temperature": 0},
  "messages": [{"role":"user","content":"지훈이 3월 14일까지 조경 도면을 마감하기로 함"}],
  "format": {
    "type": "object",
    "properties": {
      "담당자": {"type": "string"},
      "업무":   {"type": "string"},
      "기한":   {"type": "string"}
    },
    "required": ["담당자", "업무", "기한"]
  }
}' | jq -r '.message.content'
```

### OpenAI SDK 그대로 쓰기

기존 코드의 엔드포인트만 바꾸면 된다. 클라우드 API와 로컬을 A/B로 비교할 때 유용하다.

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

resp = client.chat.completions.create(
    model="llama3.1:8b",
    messages=[{"role": "user", "content": "이 문단을 세 줄로 줄여줘: ..."}],
    temperature=0.2,
)
print(resp.choices[0].message.content)
```

### 대량 배치 처리

로컬 모델의 진짜 장점은 속도가 아니라 **호출량에 비용이 안 붙는다는 점**이다. 문서 수천 건 분류처럼 API로는 부담스러운 작업에 쓴다.

```bash
for f in docs/*.md; do
  ollama run classify < "$f" >> results.tsv
done
```

순차 루프가 느리면 `OLLAMA_NUM_PARALLEL=4`로 올리고 `xargs -P 4`로 병렬화한다. 단, 4절의 컨텍스트 분할을 감안해 num_ctx를 함께 키워야 한다.

### 임베딩 (로컬 RAG)

```bash
curl http://localhost:11434/api/embed -d '{
  "model": "nomic-embed-text",
  "input": ["첫 번째 문단", "두 번째 문단"]
}'
```

임베딩 모델은 300MB~600MB 수준이라 생성 모델과 함께 올려둬도 부담이 없다.

## 7. 어디에 쓰고 어디에 쓰지 말 것

로컬이 유리한 경우는 세 가지다. 외부로 나가면 안 되는 클라이언트 문서, 호출량이 큰 반복 작업, 인터넷이 없는 환경.

반대로 복잡한 추론, 긴 코드베이스 작업, 최신 지식이 필요한 작업은 여전히 프론티어 API 쪽이 낫다. 8B 모델로 30B급 결과를 기대하고 프롬프트를 계속 손보는 것은 시간 낭비다. 두 번 고쳐서 안 되면 모델을 바꾸는 게 맞다.

## 8. 빠른 점검 체크리스트

1. `ollama ps` → `100% GPU`인가
2. `--verbose`의 tokens/s가 기준선보다 떨어지지 않았나
3. num_ctx가 실제 입력 길이에 맞게 잡혀 있나 (과하지도 부족하지도 않게)
4. 정형 작업인데 temperature가 기본값(0.8)으로 방치돼 있지 않나
5. 자주 쓰는 모델의 keep_alive가 너무 짧지 않나
6. 이 작업이 정말 이 크기의 모델을 필요로 하나

## 자주 쓰는 명령어

```bash
ollama list                 # 설치된 모델
ollama pull <model>         # 내려받기
ollama rm <model>           # 삭제 (디스크 정리)
ollama ps                   # 적재 상태·GPU 비율
ollama show <model>         # 파라미터·컨텍스트 한도 확인
ollama serve                # 서버 직접 실행 (환경변수 적용 시)
```

주요 환경변수: `OLLAMA_HOST`, `OLLAMA_MODELS`(저장 경로), `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_NUM_PARALLEL`, `OLLAMA_MAX_LOADED_MODELS`, `OLLAMA_FLASH_ATTENTION`, `OLLAMA_KV_CACHE_TYPE`.

> 버전에 따라 기본값과 지원 옵션이 달라진다. 환경변수가 먹지 않으면 `ollama --version`을 먼저 확인할 것.
