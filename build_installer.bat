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
echo [4/4] Criando pacote ZIP para distribuicao...
if not exist installer_output mkdir installer_output

powershell -Command "Compress-Archive -Path 'dist\OrionTaxSync\*' -DestinationPath 'installer_output\OrionTaxSync.zip' -Force"

if %errorlevel% neq 0 (
    echo ERRO: Falha ao criar ZIP
    pause
    exit /b 1
)
echo ✓ ZIP criado

REM Tentar tambem gerar instalador Inno Setup se disponivel
set INNO_PATH="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %INNO_PATH% set INNO_PATH="C:\Program Files\Inno Setup 6\ISCC.exe"
if not exist %INNO_PATH% set INNO_PATH="C:\Program Files (x86)\Inno Setup 5\ISCC.exe"
if not exist %INNO_PATH% set INNO_PATH="C:\Program Files\Inno Setup 5\ISCC.exe"

if exist %INNO_PATH% (
    echo.
    echo Inno Setup encontrado. Gerando instalador .exe tambem...
    %INNO_PATH% installer.iss
    if %errorlevel% equ 0 (
        echo ✓ Instalador .exe criado
    ) else (
        echo AVISO: Falha no Inno Setup - apenas ZIP gerado
    )
) else (
    echo Inno Setup nao encontrado - apenas ZIP gerado
)

echo.
echo ============================================
echo BUILD CONCLUIDO COM SUCESSO!
echo ============================================
echo.
echo ZIP:        installer_output\OrionTaxSync.zip
if exist installer_output\OrionTaxSync_Setup.exe (
    echo Instalador: installer_output\OrionTaxSync_Setup.exe
)
echo.
echo Para instalar no cliente:
echo   1. Copie OrionTaxSync.zip para o computador do cliente
echo   2. Extraia para C:\OrionTax Sync\
echo   3. Execute OrionTaxSync.exe de dentro da pasta extraida
echo.
pause