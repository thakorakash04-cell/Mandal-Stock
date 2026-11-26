#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
: "${ANDROID_PLATFORM:?Directory containing android.jar}"
: "${ANDROID_BUILD_TOOLS:?Android build-tools directory}"
: "${KEYSTORE:?Signing keystore path}"
: "${KEYSTORE_PASSWORD:?Signing password}"
: "${KEY_ALIAS:=mandalstock}"
rm -rf build/classes build/dex build/gen
mkdir -p build/classes build/dex build/gen deliverables
"$ANDROID_BUILD_TOOLS/aapt" package -f -m -M app/AndroidManifest.xml -S app/res -I "$ANDROID_PLATFORM/android.jar" -J build/gen -F build/resources.ap_
find app/src build/gen -name '*.java' > build/sources.txt
java -m jdk.compiler/com.sun.tools.javac.Main -source 8 -target 8 -encoding UTF-8 -bootclasspath "$ANDROID_PLATFORM/android.jar:$ANDROID_BUILD_TOOLS/core-lambda-stubs.jar" -d build/classes @build/sources.txt
find build/classes -name '*.class' > build/classes.txt
java -cp "$ANDROID_BUILD_TOOLS/lib/d8.jar" com.android.tools.r8.D8 --min-api 26 --lib "$ANDROID_PLATFORM/android.jar" --output build/dex @build/classes.txt
cp build/resources.ap_ build/unsigned.apk
(cd build/dex && zip -q -u ../unsigned.apk classes*.dex)
"$ANDROID_BUILD_TOOLS/zipalign" -f -p 4 build/unsigned.apk build/aligned.apk
java -jar "$ANDROID_BUILD_TOOLS/lib/apksigner.jar" sign --ks "$KEYSTORE" --ks-key-alias "$KEY_ALIAS" --ks-pass env:KEYSTORE_PASSWORD --out deliverables/Mandal-Stock-v3.0.apk build/aligned.apk
java -jar "$ANDROID_BUILD_TOOLS/lib/apksigner.jar" verify --verbose deliverables/Mandal-Stock-v3.0.apk
