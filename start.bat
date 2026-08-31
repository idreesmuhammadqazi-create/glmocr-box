@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

if exist .env for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
if not defined MODEL_QUANT set MODEL_QUANT=Q8_0
if not defined THREADS set THREADS=8
if not defined CONTEXT set CONTEXT=8192
if not defined OCR_API_KEY set OCR_API_KEY=changeme-please
if not defined PORT set PORT=8000

if not exist "llama-bin\llama-server.exe" (echo Run setup.bat first & pause & exit /b 1)

echo Starting llama-server (GPU via Vulkan) ...
start "glmocr-llama" /min llama-bin\llama-server.exe -m models\GLM-OCR-%MODEL_QUANT%.gguf --mmproj models\mmproj-GLM-OCR-%MODEL_QUANT%.gguf --host 127.0.0.1 --port 8080 -c %CONTEXT% -ngl 99 --alias glm-ocr --flash-attn off -fit off --threads %THREADS%

:waitllama
timeout /t 2 /nobreak >nul
curl -s http://127.0.0.1:8080/health | findstr /c:"ok" >nul 2>&1
if errorlevel 1 goto waitllama
echo llama-server is up.

echo Starting OCR pipeline (layout on CPU) ...
start "glmocr-pipeline" /min .venv\Scripts\python.exe -m glmocr.server --config config-windows.yaml

:waitocr
timeout /t 2 /nobreak >nul
curl -s http://127.0.0.1:5002/health | findstr /c:"ok" >nul 2>&1
if errorlevel 1 goto waitocr
echo glmocr pipeline is up.

echo.
echo ============================================================
echo  API ready:  http://127.0.0.1:%PORT%/paas/v4/layout_parsing
echo  Auth:       Authorization: Bearer %OCR_API_KEY%
echo  Stop:       close this window and the two minimized ones
echo ============================================================
echo.

.venv\Scripts\python.exe -m uvicorn shim.app:app --host 0.0.0.0 --port %PORT%
