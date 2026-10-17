@echo off
chcp 65001 >nul
rem ============================================================
rem  Mech QBank APK one-click build (overwrite mech-qbank.apk)
rem  Cloned from build_hub_apk.bat. Web assets come from
rem  E:\agent\mech-qbank\web\  (index.html + qbank-data.js + qbank-static.js)
rem  Regenerate data: python E:\agent\mech-qbank\tools\make_webdata.py
rem  NOTE: keep this file pure ASCII - cmd.exe reads .bat as GBK.
rem Requires: JDK17 + Android SDK already set up in build-tools
rem ============================================================
cd /d E:\agent\androd-app\qbank-app
set "JAVA_HOME=E:\agent\androd-app\build-tools\jdk-17.0.2"
set "ANDROID_HOME=E:\agent\androd-app\build-tools\android-sdk"
echo Building release APK...
call E:\agent\androd-app\build-tools\gradle-8.7\bin\gradle.bat assembleRelease --no-daemon
if errorlevel 1 (
    echo.
    echo BUILD FAILED - see messages above.
    pause
    exit /b 1
)
copy /y "app\build\outputs\apk\release\app-release.apk" "E:\agent\androd-app\apk\mech-qbank.apk" >nul
echo.
echo Done! APK: E:\agent\androd-app\apk\mech-qbank.apk
echo Send it to your phone and install.
