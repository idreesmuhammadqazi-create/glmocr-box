@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set MODEL_QUANT=Q8_0
set LLAMA_DIR=llama-bin
set VENV=.venv

echo === glmocr-box native Windows setup ===

py -3 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3 not found. Install Python 3.10-3.12 from https://www.python.org/downloads/windows/
  echo and CHECK "Add python.exe to PATH" during install, then re-run this file.
  pause & exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
  echo [1/5] Creating Python virtual environment ...
  py -3 -m venv %VENV% || (pause & exit /b 1)
)

echo [2/5] Installing packages (CPU torch + GLM-OCR SDK + shim) ...
call %VENV%\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu || (pause & exit /b 1)
pip install --no-cache-dir "glmocr[selfhosted,server]" fastapi "uvicorn[standard]" httpx pymupdf pillow || (pause & exit /b 1)

if not exist %LLAMA_DIR% mkdir %LLAMA_DIR%
if not exist %LLAMA_DIR%\llama-server.exe (
  echo [3/5] Downloading llama.cpp Vulkan build for Windows ...
  set "LLAMA_URL=https://github.com/ggml-org/llama.cpp/releases/download/b10715/llama-b10715-bin-win-vulkan-x64.zip"
  for /f "usebackq delims=" %%u in (`powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { $rels = Invoke-RestMethod 'https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10'; foreach ($r in $rels) { $a = $r.assets | Where-Object { $_.name -match 'bin-win-vulkan-x64\.zip$' } | Select-Object -First 1; if ($a) { $a.browser_download_url; break } } } catch { }"`) do if not "%%u"=="" set "LLAMA_URL=%%u"
  echo Using: !LLAMA_URL!
  powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '!LLAMA_URL!' -OutFile 'llama-bin\llama.zip'" || (echo Download failed & pause & exit /b 1)
  powershell -NoProfile -Command "Expand-Archive -Force 'llama-bin\llama.zip' 'llama-bin\tmp'" || (echo Extract failed & pause & exit /b 1)
  for /r llama-bin\tmp %%f in (llama-server.exe) do copy /y "%%f" llama-bin\ >nul
  for /r llama-bin\tmp %%f in (*.dll) do copy /y "%%f" llama-bin\ >nul
  rmdir /s /q llama-bin\tmp
  del llama-bin\llama.zip
  if not exist llama-bin\llama-server.exe (echo llama-server.exe not found in archive & pause & exit /b 1)
)

if not exist models mkdir models
if not exist models\GLM-OCR-%MODEL_QUANT%.gguf (
  echo [4/5] Downloading GLM-OCR %MODEL_QUANT% model (~1.3 GB) ...
  curl -fL --retry 3 -o models\GLM-OCR-%MODEL_QUANT%.gguf.part "https://huggingface.co/ggml-org/GLM-OCR-GGUF/resolve/main/GLM-OCR-%MODEL_QUANT%.gguf"
  move models\GLM-OCR-%MODEL_QUANT%.gguf.part models\GLM-OCR-%MODEL_QUANT%.gguf >nul
)
if not exist models\mmproj-GLM-OCR-%MODEL_QUANT%.gguf (
  echo [4/5] Downloading GLM-OCR vision projector (~0.9 GB) ...
  curl -fL --retry 3 -o models\mmproj-GLM-OCR-%MODEL_QUANT%.gguf.part "https://huggingface.co/ggml-org/GLM-OCR-GGUF/resolve/main/mmproj-GLM-OCR-%MODEL_QUANT%.gguf"
  move models\mmproj-GLM-OCR-%MODEL_QUANT%.gguf.part models\mmproj-GLM-OCR-%MODEL_QUANT%.gguf >nul
)

echo [5/5] Done. Run start.bat to launch the API.
pause
