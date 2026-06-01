#!/bin/bash
# 고정 자가서명 코드서명 인증서 + 전용 키체인을 1회 만든다.
# 목적: build_app.sh 가 ad-hoc(-s -) 대신 이 고정 신원으로 서명하면, 재빌드해도 앱
#       designated requirement 가 안정돼 macOS 권한(마이크/손쉬운 사용)이 유지된다.
# 개인키는 레포 밖(~/.qwen-dictation/signing)에 둔다. 멱등(이미 있으면 건너뜀).
#
# 주의: 마지막 "신뢰(trust)" 단계는 macOS 보안상 GUI 세션에서만 가능하다(원격/SSH 불가).
#       이 스크립트(헤드리스)는 인증서·키체인·import 까지만 하고, 신뢰 등록은
#       바탕화면의 Qwen서명신뢰.command 를 더블클릭해 1회 승인한다.
set -uo pipefail

SIGN_DIR="$HOME/.qwen-dictation/signing"
KEYCHAIN="$SIGN_DIR/qwen-signing.keychain-db"
PW_FILE="$SIGN_DIR/keychain.pw"
CERT_CN="Qwen Dictation Local Signing"
GEN_OPENSSL=/opt/homebrew/bin/openssl   # cert 생성(OpenSSL3 ok)
[ -x "$GEN_OPENSSL" ] || GEN_OPENSSL=/usr/bin/openssl
P12_OPENSSL=/usr/bin/openssl            # p12 export 는 macOS 호환 위해 LibreSSL 사용

mkdir -p "$SIGN_DIR"; chmod 700 "$SIGN_DIR"

if [ -f "$KEYCHAIN" ] && [ -f "$PW_FILE" ] && \
   security find-identity -p codesigning "$KEYCHAIN" 2>/dev/null | grep -q "$CERT_CN"; then
  echo "ALREADY_SET_UP: '$CERT_CN' 이미 존재. (신뢰 미등록이면 Qwen서명신뢰.command 더블클릭)"
  exit 0
fi

if [ -f "$PW_FILE" ]; then KCPW=$(cat "$PW_FILE"); else
  KCPW=$(/usr/bin/openssl rand -hex 16); printf '%s' "$KCPW" > "$PW_FILE"; chmod 600 "$PW_FILE"; fi

# 1) 자가서명 codesigning 인증서
"$GEN_OPENSSL" req -x509 -newkey rsa:2048 -nodes \
  -keyout "$SIGN_DIR/key.pem" -out "$SIGN_DIR/cert.pem" -days 3650 \
  -subj "/CN=$CERT_CN" \
  -addext "basicConstraints=critical,CA:false" \
  -addext "keyUsage=critical,digitalSignature" \
  -addext "extendedKeyUsage=critical,codeSigning" || { echo "FAIL: cert 생성"; exit 1; }
# p12 (LibreSSL = Apple security import 호환)
"$P12_OPENSSL" pkcs12 -export -inkey "$SIGN_DIR/key.pem" -in "$SIGN_DIR/cert.pem" \
  -out "$SIGN_DIR/cert.p12" -passout "pass:$KCPW" -name "$CERT_CN" || { echo "FAIL: p12"; exit 1; }

# 2) 전용 키체인 + import + partition list(프롬프트 없이 codesign 키 접근) + 검색목록
security delete-keychain "$KEYCHAIN" 2>/dev/null || true
security create-keychain -p "$KCPW" "$KEYCHAIN"
security set-keychain-settings "$KEYCHAIN"
security unlock-keychain -p "$KCPW" "$KEYCHAIN"
security import "$SIGN_DIR/cert.p12" -k "$KEYCHAIN" -P "$KCPW" -T /usr/bin/codesign -T /usr/bin/security
security set-key-partition-list -S apple-tool:,apple: -s -k "$KCPW" "$KEYCHAIN" >/dev/null 2>&1
CUR=$(security list-keychains -d user | sed 's/[" ]//g')
echo "$CUR" | grep -q "qwen-signing" || security list-keychains -d user -s $CUR "$KEYCHAIN"

rm -f "$SIGN_DIR/key.pem"   # 평문 개인키 제거(키는 키체인에 있음)

echo "OK: 인증서·키체인 준비 완료."
security find-identity -p codesigning "$KEYCHAIN" | grep "$CERT_CN" || true
echo ""
echo ">>> 남은 1단계(GUI): 바탕화면 'Qwen서명신뢰.command' 더블클릭 → 맥 암호 입력."
echo "    (자가서명 인증서를 코드서명용으로 신뢰 등록. 원격/SSH 에선 불가능한 단계.)"
