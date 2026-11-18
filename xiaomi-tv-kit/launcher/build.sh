#!/bin/bash
# 无 gradle 打包：aapt2 → javac → d8 → zipalign → apksigner
set -e
cd "$(dirname "$0")"
[ -n "$JAVA_HOME" ] && export PATH=$JAVA_HOME/bin:$PATH; SDK=${ANDROID_HOME:-$HOME/Android/sdk}; BT=$SDK/build-tools/34.0.0; JAR=$SDK/platforms/android-28/android.jar
mkdir -p assets; rm -rf out && mkdir -p out/cls out/gen
$BT/aapt2 compile --dir res -o out/res.zip
$BT/aapt2 link -I $JAR --manifest AndroidManifest.xml -A assets -o out/base.apk --java out/gen out/res.zip
javac --release 8 -nowarn -cp $JAR -d out/cls $(find . -maxdepth 1 -name "*.java") $(find out/gen -name "*.java") 2>&1 | grep -v 'warning' || true
$BT/d8 --release --lib $JAR --min-api 21 --output out $(find out/cls -name '*.class')
cp out/base.apk out/u.apk && (cd out && zip -q u.apk classes.dex)
$BT/zipalign -f 4 out/u.apk out/a.apk
KS=$HOME/.android/tvkit.jks
[ -f $KS ] || keytool -genkeypair -keystore $KS -storepass android -keypass android -alias k -keyalg RSA -keysize 2048 -validity 36500 -dname CN=tvhome >/dev/null 2>&1
$BT/apksigner sign --ks $KS --ks-pass pass:android --out out/tvhome.apk out/a.apk
echo built: $(pwd)/out/tvhome.apk
