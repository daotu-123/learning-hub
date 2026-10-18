@echo off
chcp 65001 >nul
setlocal
rem ============================================================
rem  Single APK build: web (Vue) -> android assets -> signed APK
rem  Usage:
rem    build_apk.bat              full build (npm build + gradle)
rem    build_apk.bat -skip-web    reuse existing server/web_dist/app
rem ============================================================
cd /d "%~dp0"
set "JAVA_HOME=%~dp0build-tools\jdk-17.0.2"
set "ANDROID_HOME=%~dp0build-tools\android-sdk"
set "GRADLE=%~dp0build-tools\gradle-8.7\bin\gradle.bat"

if /i "%1"=="-skip-web" goto assets

echo [1/4] building web (vue-tsc + vite)...
pushd web
call npm run build
if errorlevel 1 (
    popd
    echo BUILD FAILED: web build error.
    exit /b 1
)
popd

:assets
echo [2/4] syncing dist to android assets...
if exist "android\app\src\main\assets\www" rmdir /s /q "android\app\src\main\assets\www"
xcopy /e /i /q "server\web_dist\app" "android\app\src\main\assets\www" >nul
if errorlevel 1 (
    echo BUILD FAILED: sync assets error.
    exit /b 1
)

echo [3/4] bumping web VERSION...
set "VER=1"
if exist "server\web_dist\VERSION" set /p VER=<"server\web_dist\VERSION"
set /a VER=VER+1
> "server\web_dist\VERSION" <nul set /p "=%VER%"
echo   VERSION = %VER%

echo [4/4] gradle assembleRelease...
pushd android
call "%GRADLE%" assembleRelease --no-daemon
if errorlevel 1 (
    popd
    echo BUILD FAILED: gradle error.
    exit /b 1
)
popd

copy /y "android\app\build\outputs\apk\release\app-release.apk" "apk\学习中枢.apk" >nul
echo.
echo Done: apk\学习中枢.apk
for %%A in ("apk\学习中枢.apk") do echo Size: %%~zA bytes
endlocal
