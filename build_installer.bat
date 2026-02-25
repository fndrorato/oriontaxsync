@echo off
echo ============================================
echo OrionTax Sync - Build Instalador
echo ============================================
echo.

REM Ativar ambiente virtual
echo [0/4] Ativando ambiente virtual...
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
    echo ✓ Ambiente virtual ativado
) else (
    echo ERRO: Ambiente virtual nao encontrado!
    echo Por favor, crie o ambiente virtual primeiro: python -m venv venv
    pause
    exit /b 1
)

echo.
echo [1/4] Limpando builds anteriores...
if exist build rmdir /s /q build 2>nul
if exist dist rmdir /s /q dist 2>nul
if exist installer_output rmdir /s /q installer_output 2>nul
echo ✓ Cache limpo

echo.
echo [2/4] Verificando dependencias...
python --version
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller nao encontrado. Instalando...
    pip install pyinstaller
)
echo ✓ Dependencias OK

echo.
echo [3/4] Compilando executavel (PyInstaller)...
pyinstaller build.spec --clean --noconfirm

if %errorlevel% neq 0 (
    echo ERRO: Falha ao compilar executavel
    pause
    exit /b 1
)
echo ✓ Executavel compilado

echo.
echo [4/4] Criando instalador (Inno Setup)...
set INNO_PATH="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %INNO_PATH% (
    set INNO_PATH="C:\Program Files\Inno Setup 6\ISCC.exe"
)

if not exist %INNO_PATH% (
    echo.
    echo AVISO: Inno Setup nao encontrado!
    echo Por favor, instale o Inno Setup de: https://jrsoftware.org/isdl.php
    echo.
    echo O executavel foi compilado com sucesso em: dist\OrionTaxSync\
    pause
    exit /b 0
)

%INNO_PATH% installer.iss

if %errorlevel% neq 0 (
    echo ERRO: Falha ao criar instalador
    pause
    exit /b 1
)

echo.
echo ============================================
echo BUILD CONCLUIDO COM SUCESSO!
echo ============================================
echo.
echo Executavel: dist\OrionTaxSync\OrionTaxSync.exe
echo Instalador: installer_output\OrionTaxSync_Setup.exe
echo.
echo Tamanho dos arquivos:
dir /s dist\OrionTaxSync\OrionTaxSync.exe | find "OrionTaxSync.exe"
if exist installer_output\OrionTaxSync_Setup.exe (
    dir /s installer_output\OrionTaxSync_Setup.exe | find "OrionTaxSync_Setup.exe"
)
echo.
pause