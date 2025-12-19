#!/usr/bin/env python3
"""
Script para gerar executável do OrionTax Sync
"""
import subprocess
import sys
import os
import shutil


def clean_build():
    """Remove diretórios de build anteriores"""
    print("🧹 Limpando builds anteriores...")
    
    dirs_to_remove = ['build', 'dist']
    
    for dir_name in dirs_to_remove:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"   Removido: {dir_name}/")
    
    print("✓ Limpeza concluída\n")


def build_executable():
    """Gera executável usando PyInstaller"""
    print("🔨 Gerando executável...")
    print("="*80)
    
    try:
        # Comando PyInstaller
        cmd = [
            'pyinstaller',
            '--clean',
            '--noconfirm',
            'build.spec'
        ]
        
        print(f"Comando: {' '.join(cmd)}\n")
        
        # Executar PyInstaller
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        
        print(result.stdout)
        
        if result.returncode == 0:
            print("\n" + "="*80)
            print("✅ Build concluído com sucesso!")
            print("="*80)
            print(f"\n📦 Executável gerado em: dist/OrionTaxSync/")
            print(f"📄 Arquivo principal: dist/OrionTaxSync/OrionTaxSync.exe")
            
            # Verificar tamanho
            exe_path = 'dist/OrionTaxSync/OrionTaxSync.exe'
            if os.path.exists(exe_path):
                size_mb = os.path.getsize(exe_path) / (1024 * 1024)
                print(f"📊 Tamanho: {size_mb:.2f} MB\n")
        else:
            print("\n❌ Erro no build!")
            print(result.stderr)
            sys.exit(1)
            
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Erro ao executar PyInstaller: {e}")
        print(e.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erro inesperado: {e}")
        sys.exit(1)


def create_installer_script():
    """Cria script para criar instalador (opcional)"""
    print("\n📝 Criando script de instalação...")
    
    # Criar script .iss para Inno Setup (se quiser criar instalador)
    iss_content = """
; Script Inno Setup para OrionTax Sync

[Setup]
AppName=OrionTax Sync
AppVersion=1.0
DefaultDirName={pf}\\OrionTaxSync
DefaultGroupName=OrionTax Sync
OutputDir=installer
OutputBaseFilename=OrionTaxSync_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin

[Files]
Source: "dist\\OrionTaxSync\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\\OrionTax Sync"; Filename: "{app}\\OrionTaxSync.exe"
Name: "{group}\\Desinstalar OrionTax Sync"; Filename: "{uninstallexe}"
Name: "{commonstartup}\\OrionTax Sync"; Filename: "{app}\\OrionTaxSync.exe"; Comment: "Iniciar OrionTax Sync automaticamente"

[Run]
Filename: "{app}\\OrionTaxSync.exe"; Description: "Iniciar OrionTax Sync"; Flags: nowait postinstall skipifsilent
"""
    
    with open('installer.iss', 'w', encoding='utf-8') as f:
        f.write(iss_content)
    
    print("✓ Script installer.iss criado")
    print("   Para criar instalador, instale Inno Setup e execute: iscc installer.iss\n")


def create_startup_script():
    """Cria script .bat para adicionar ao startup do Windows"""
    print("📝 Criando script de startup...")
    
    bat_content = """@echo off
REM Script para iniciar OrionTax Sync

start "" "%~dp0OrionTaxSync.exe"
"""
    
    output_path = 'dist/OrionTaxSync/start_oriontax.bat'
    
    if os.path.exists('dist/OrionTaxSync'):
        with open(output_path, 'w') as f:
            f.write(bat_content)
        
        print(f"✓ Script criado: {output_path}")
        print("   Copie para: C:\\Users\\[Usuario]\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\n")


def main():
    """Função principal"""
    print("\n" + "="*80)
    print("🚀 OrionTax Sync - Build System")
    print("="*80 + "\n")
    
    # 1. Limpar builds anteriores
    clean_build()
    
    # 2. Gerar executável
    build_executable()
    
    # 3. Criar scripts adicionais
    create_installer_script()
    create_startup_script()
    
    print("\n" + "="*80)
    print("✅ PROCESSO CONCLUÍDO!")
    print("="*80)
    print("\n📋 Próximos passos:")
    print("   1. Teste o executável: dist/OrionTaxSync/OrionTaxSync.exe")
    print("   2. (Opcional) Crie instalador com Inno Setup: iscc installer.iss")
    print("   3. Para iniciar com Windows, copie start_oriontax.bat para pasta Startup")
    print("\n")


if __name__ == '__main__':
    main()