@echo off
chcp 65001 >nul
echo ============================================
echo   GitHub 同步监控 —— PyInstaller 打包脚本
echo ============================================
echo.

REM 检查 PyInstaller
pyinstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [信息] 未找到 PyInstaller，正在安装...
    pip install pyinstaller --break-system-packages
    if %errorlevel% neq 0 (
        echo [错误] PyInstaller 安装失败，请手动执行：
        echo   pip install pyinstaller --break-system-packages
        pause
        exit /b 1
    )
)

REM 清理旧构建
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

echo [1/2] 正在打包为单个 .exe 文件（这可能需要几分钟）...
echo.

pyinstaller ^
    --onefile ^
    --windowed ^
    --name "GitHub同步监控" ^
    --hidden-import pystray ^
    --hidden-import pystray._win32 ^
    --hidden-import PIL ^
    --hidden-import PIL.Image ^
    --hidden-import PIL.ImageDraw ^
    --hidden-import watchdog.observers ^
    --hidden-import watchdog.events ^
    --noconfirm ^
    --clean ^
    main.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] 打包失败！请检查错误信息。
    echo.
    echo 常见问题：
    echo   1. 请先运行 pip install -r requirements.txt 安装依赖
    echo   2. PyInstaller 需要 5.0 以上版本
    pause
    exit /b 1
)

echo.
echo [2/2] 打包完成！
echo.
echo ============================================
echo   输出文件: dist\GitHub同步监控.exe
echo ============================================
echo.
echo 使用说明：
echo   1. 将 "GitHub同步监控.exe" 放到任意目录双击运行
echo   2. 首次运行会在 exe 同目录下自动生成 config.json
echo   3. 确保电脑已安装 Git 并配置好 GitHub SSH/HTTPS 认证
echo   4. 关闭窗口不会退出程序，请在托盘图标右键退出
echo.
pause
