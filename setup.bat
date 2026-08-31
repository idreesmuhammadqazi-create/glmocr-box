@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set MODEL_QUANT=Q8_0
set LLAMA_DIR=llama-bin
set VENV=.venv
set LLAMA_URL=https://github.com/ggml-org/llama.cpp/releases/download/b10715/llama-b10715-bin-win-vulkan-x64.zip

echo === glmocr-box native Windows setup ===

py -3 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3 not found. Install Python 3.10-3.12 from https://www.python.org/downloads/windows/
  echo and CHECK "Add python.exe to PATH" during install, then re-run this file.
  pause
  exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
  echo [1/5] Creating Python virtual environment ...
  py -3 -m venv %VENV%
  if errorlevel 1 goto :fail
)

echo [2/5] Installing packages (CPU torch + GLM-OCR SDK + shim) ...
call %VENV%\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto :fail
pip install --no-cache-dir "glmocr[selfhosted,server]" fastapi "uvicorn[standard]" httpx pymupdf pillow
if errorlevel 1 goto :fail

if not exist %LLAMA_DIR% mkdir %LLAMA_DIR%
if exist %LLAMA_DIR%\llama-server.exe goto :models

echo [3/5] Downloading llama.cpp Vulkan build for Windows ...
echo URL: %LLAMA_URL%
curl -fL --retry 3 -o %LLAMA_DIR%\llama.zip %LLAMA_URL%
if errorlevel 1 goto :fail
powershell -NoProfile -Command "Expand-Archive -Force 'llama-bin\llama.zip' 'llama-bin\tmp'"
if errorlevel 1 goto :fail
for /r %LLAMA_DIR%\tmp %%f in (llama-server.exe) do copy /y "%%f" %LLAMA_DIR%\ >nul
for /r %LLAMA_DIR%\tmp %%f in (*.dll) do copy /y "%%f" %LLAMA_DIR%\ >nul
rmdir /s /q %LLAMA_DIR%\tmp
del %LLAMA_DIR%\llama.zip
if not exist %LLAMA_DIR%\llama-server.exe goto :fail

:models
if not exist models mkdir models
if exist models\GLM-OCR-%MODEL_QUANT%.gguf goto :mmproj
echo [4/5] Downloading GLM-OCR %MODEL_QUANT% model (~1.3 GB) ...
curl -fL --retry 3 -o models\GLM-OCR-%MODEL_QUANT%.gguf.part https://huggingface.co/ggml-org/GLM-OCR-GGUF/resolve/main/GLM-OCR-%MODEL_QUANT%.gguf
if errorlevel 1 goto :fail
move models\GLM-OCR-%MODEL_QUANT%.gguf.part models\GLM-OCR-%MODEL_QUANT%.gguf >nul

:mmproj
if exist models\mmproj-GLM-OCR-%MODEL_QUANT%.gguf goto :done
echo [4/5] Downloading GLM-OCR vision projector (~0.9 GB) ...
curl -fL --retry 3 -o models\mmproj-GLM-OCR-%MODEL_QUANT%.gguf.part https://huggingface.co/ggml-org/GLM-OCR-GGUF/resolve/main/mmproj-GLM-OCR-%MODEL_QUANT%.gguf
if errorlevel 1 goto :fail
move models\mmproj-GLM-OCR-%MODEL_QUANT%.gguf.part models\mmproj-GLM-OCR-%MODEL_QUANT%.gguf >nul

:done
echo [5/5] Done. Run start.bat to launch the API.
pause
exit /b 0

:fail
echo.
echo Setup failed. Read the error above, fix it, and re-run setup.bat - completed steps are skipped.
pause
exit /b 1
