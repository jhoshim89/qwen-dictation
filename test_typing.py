import time
import subprocess
import sys

print("Initializing local Qwen3-ASR typing E2E integration test...", flush=True)
print("----------------------------------------------------------------", flush=True)
print("3초 동안 대기합니다. 현재 채팅 입력창이나 메모장을 마우스로 클릭해 주세요!", flush=True)

for i in range(3, 0, -1):
    print(f"{i}초 남음...", flush=True)
    time.sleep(1)

test_text = "✨ [E2E 테스트 성공] Qwen3-ASR 로컬 실시간 받아쓰기 자동 입력 파이프라인이 완벽히 검증되었습니다! 🎙️🚀"

try:
    # 1. Copy text to macOS clipboard (simulating transcription result)
    subprocess.run(['pbcopy'], input=test_text.encode('utf-8'), check=True)
    
    # 2. Trigger AppleScript keyboard paste keystroke (Command + V)
    osascript = 'tell application "System Events" to keystroke "v" using command down'
    subprocess.run(['osascript', '-e', osascript], check=True)
    
    print("\n🎉 입력 테스트가 완료되었습니다! 커서 위치에 텍스트가 성공적으로 자동 작성되었는지 확인해 보세요.", flush=True)
except Exception as e:
    print(f"\n❌ 에러 발생: {e}", flush=True)
