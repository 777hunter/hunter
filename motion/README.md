# 동영상 모션 인식 / 동작 분석

동영상 파일을 넣으면 프레임마다 사람 관절 33개를 뽑아 관절 각도, 반복 횟수,
움직임 구간을 계산하고 스켈레톤을 덧씌운 영상까지 내보내는 CLI.

## 뭘 쓸지 먼저

동작 분석은 접근이 세 갈래고, 목적에 따라 답이 다르다.

1. **키포인트(포즈 추정) + 규칙** — 지금 이 폴더가 하는 방식.
   MediaPipe Pose로 관절 좌표를 뽑고 각도·속도로 규칙을 세운다.
   CPU만으로 실시간에 가깝고, "왜 그렇게 판정했는지"가 각도로 설명된다.
   스쿼트 개수, 무릎 각도 부족, 좌우 비대칭 같은 정량 피드백에 맞다.
   한계: 동작 이름을 스스로 배우지 못하고, 사람마다 임계값을 손봐야 한다.

2. **영상 분류 모델** — VideoMAE, X3D, SlowFast 같은 3D CNN/트랜스포머에
   클립을 통째로 넣어 "스쿼트/데드리프트/걷기"를 분류한다. 라벨링된 학습
   데이터와 GPU가 필요하지만, 규칙으로 못 쓰는 미묘한 동작을 잡는다.
   HuggingFace `videomae-base-finetuned-kinetics`로 바로 시험해볼 수 있다.

3. **키포인트 시퀀스 분류** — 1번으로 뽑은 좌표 시퀀스를 LSTM/GCN
   (ST-GCN, PoseC3D)에 넣는다. 배경·의상에 안 흔들리고 학습 데이터가 훨씬
   적게 든다. 커스텀 동작 몇 개를 인식시켜야 할 때 가성비가 제일 좋다.

**추천 순서**: 1번으로 시작해서 각도 규칙으로 안 되는 게 뭔지 확인한 뒤,
그때 3번으로 넘어간다. 2번은 라벨 데이터가 이미 있을 때만.

여러 명이 동시에 나오거나 정확도가 더 필요하면 포즈 추정기를 YOLO11-pose
또는 RTMPose로 바꾸면 된다. 아래 코드는 `pose_core.py`의 추출부만 갈아끼우면
나머지 분석 로직을 그대로 쓸 수 있게 나눠 놨다.

## 설치

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r motion/requirements.txt
# 리눅스 헤드리스 서버라면 EGL 런타임이 필요하다
sudo apt-get install -y libegl1 libgl1 libgles2
```

모델(`pose_landmarker_*.task`)은 첫 실행 때 `~/.cache/mediapipe`로 자동
다운로드된다. 오프라인이면 `--model` 로 경로를 직접 준다.

## 사용

```bash
python motion/analyze.py squat.mp4 --out-dir out --exercise squat --annotate
```

주요 옵션

| 옵션 | 설명 |
| --- | --- |
| `--exercise` | `auto`(전부 시도) 또는 `squat pushup curl situp jumping_jack` 중 복수 지정 |
| `--model-variant` | `lite`(빠름) / `full`(기본) / `heavy`(정확) |
| `--stride N` | N프레임마다 1장만 처리. 긴 영상 훑을 때 |
| `--annotate` | 스켈레톤·각도·카운트 오버레이 mp4 저장 |
| `--dump-landmarks` | CSV에 33개 키포인트 원본 좌표까지 포함 |

## 출력

- `*_frames.csv` — 프레임별 8개 관절 각도, 상체 기울기, 정규화된 움직임 속도
- `*_summary.json` — 반복 횟수와 각 반복의 시각, 관절 각도 min/max/mean,
  좌우 비대칭, 움직임이 있었던 구간(초 단위), 검출률
- `*_annotated.mp4` — 눈으로 검증할 오버레이 영상

`detection_rate`가 0.9 아래면 결과를 믿지 마라. 대개 사람이 프레임 밖으로
나가거나, 옆모습이라 반대쪽 관절이 가려졌거나, 조명이 문제다.

## 반복 카운트가 동작하는 방식

관절 각도 신호에 결측 보간 + 이동평균을 걸고, 히스테리시스 2단
임계값(`low`/`high`)으로 상태 기계를 돌린다. `high → low → high`가 1회.
한 임계값만 쓰면 노이즈로 중복 카운트가 나기 때문에 두 개를 쓴다.
임계값은 `metrics.py`의 `EXERCISES`에 모아 뒀고, 촬영 각도나 대상자에 따라
여기만 고치면 된다. 새 동작을 추가할 때도 신호 함수 하나 + 임계값 두 개면 끝.

## 알려진 한계

- 한 명만 추적한다(`num_poses=1`). 여러 명이면 위 2번 항목대로 교체.
- 카메라가 정면/측면 어느 쪽이냐에 따라 각도가 달라진다. 스쿼트 무릎 각도는
  측면, 좌우 비대칭은 정면이 정확하다.
- 3D 월드 좌표는 골반 기준 상대 좌표라 절대 위치·실제 이동거리는 못 준다.
- 손가락·표정은 별도 모델(HandLandmarker, FaceLandmarker)이 필요하다.
