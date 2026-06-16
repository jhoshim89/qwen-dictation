# Qwen vs Nemotron ASR 비교 메모

테스트 일시: 2026-06-11

## 구현 결론

- 기본 엔진은 `qwen`을 유지한다.
- 대시보드의 음성 인식 섹션에서 `qwen` / `nemotron_mlx`를 스위칭할 수 있다.
- Qwen은 commit-time `context=` bias를 계속 사용한다.
- Nemotron MLX는 Qwen과 같은 context API가 없어 모델에는 context를 넣지 않고, 공통 사후 용어 보정만 적용한다.

## 합성 벤치 결과

테스트셋은 macOS `say`로 만든 작은 smoke set이다. 실제 마이크·잡음·화자 데이터가 아니므로 최종 품질 판정용이 아니라 “로컬 실행 가능성, 대략적인 속도, 명백한 정확도 차이” 확인용이다.

한국어 2개, `--language ko`, preload + untimed warm transcription 후 측정:

| 엔진 | mean CER | mean WER | median |
| --- | ---: | ---: | ---: |
| Qwen3-ASR 1.7B | 0.018 | 0.062 | 0.51s |
| Nemotron 3.5 ASR 0.6B (MLX) | 0.036 | 0.134 | 0.08s |

영어 1개, `--language en`, preload + warm 후 측정:

| 엔진 | mean CER | mean WER | median |
| --- | ---: | ---: | ---: |
| Qwen3-ASR 1.7B | 0.000 | 0.000 | 0.22s |
| Nemotron 3.5 ASR 0.6B (MLX) | 0.000 | 0.000 | 0.15s |

## 판단

현재 앱의 주 사용 케이스가 한국어 받아쓰기와 전문용어 bias라면 Qwen이 더 안전하다. Nemotron은 매우 빠르고 영어 smoke test도 좋지만, 한국어 합성 샘플에서 Qwen보다 오탈자가 더 많았고 context hotword API가 없다.

추천 운영:

- 기본값: `qwen`
- 빠른 영어/일반 dictation 실험: `nemotron_mlx`
- 실제 전환 판단: 사용자의 실제 마이크 문장 20-50개로 `compare_asr.py` 재실행

## 재현 명령

```bash
./venv/bin/python compare_asr.py /tmp/qwen_nemotron_bench --language ko --limit 2 --output /tmp/qwen_nemotron_compare_ko.csv
./venv/bin/python compare_asr.py /tmp/qwen_nemotron_bench_en --language en --output /tmp/qwen_nemotron_compare_en.csv
```
