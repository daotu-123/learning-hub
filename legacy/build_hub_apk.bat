@echo off
chcp 65001 >nul
rem ============================================================
rem  Learning Hub APK one-click build (overwrite 学习中枢.apk)
rem  Requires: JDK17 + Android SDK already set up in build-tools
rem ============================================================
cd /d E:\agent\androd-app\hub-app
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
copy /y "app\build\outputs\apk\release\app-release.apk" "E:\agent\androd-app\apk\学习中枢.apk" >nul
echo.
echo Done! APK: E:\agent\androd-app\apk\学习中枢.apk
echo Send it to your phone and install.
pause
