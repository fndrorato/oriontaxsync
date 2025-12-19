#!/usr/bin/env python3
"""
OrionTax Sync - Sistema de Sincronização
"""
import sys
import logging
from pathlib import Path
from datetime import datetime
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt
from config.database import DatabaseManager
from gui.login import LoginDialog
from gui.main_window import MainWindow
from core.scheduler import Scheduler

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

def setup_logging():
    """Configura sistema de logging"""
    # Criar pasta logs
    log_dir = Path(__file__).parent / 'logs'
    log_dir.mkdir(exist_ok=True)
    
    # Nome do arquivo com data/hora
    log_filename = log_dir / f'oriontax_{datetime.now().strftime("%Y%m%d")}.log'
    
    # Formato
    log_format = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # Configurar
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=[
            # Console
            logging.StreamHandler(sys.stdout),
            # Arquivo (rotativo por dia)
            logging.FileHandler(log_filename, encoding='utf-8')
        ]
    )

class OrionTaxSyncApp:
    """Aplicação principal com System Tray"""
    
    def __init__(self):
        setup_logging()
        
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)  # ✅ Não fechar ao fechar janela
        
        self.db_manager = None
        self.scheduler = None
        self.main_window = None
        self.tray_icon = None
        
        # Inicializar sistema
        self.init_database()
        self.init_scheduler()
        self.init_tray()
        
        # ✅ SEMPRE MOSTRAR LOGIN AO INICIAR
        self.show_login()
    
    def init_database(self):
        """Inicializa banco de dados"""
        try:
            logger.info("="*80)
            logger.info("OrionTax Sync - Iniciando Sistema")
            logger.info("="*80)
            
            logger.info("Conectando ao banco de dados...")
            self.db_manager = DatabaseManager()
            self.db_manager.connect()
            logger.info("✓ Banco de dados conectado")
            
        except Exception as e:
            logger.error(f"Erro ao inicializar banco: {e}")
            sys.exit(1)
    
    def init_scheduler(self):
        """Inicializa scheduler"""
        try:
            logger.info("Iniciando agendador de tarefas...")
            self.scheduler = Scheduler(self.db_manager)
            self.scheduler.start()
            logger.info("✓ Scheduler iniciado")
            
            jobs = self.scheduler.get_jobs()
            if jobs:
                logger.info(f"{len(jobs)} job(s) agendado(s)")
            else:
                logger.info("Nenhum job agendado no momento")
                
        except Exception as e:
            logger.error(f"Erro ao iniciar scheduler: {e}")
    
    def init_tray(self):
        """Inicializa System Tray Icon"""
        try:
            # Criar ícone do system tray
            self.tray_icon = QSystemTrayIcon(self.app)
            
            # Usar ícone padrão
            icon = self.app.style().standardIcon(self.app.style().SP_ComputerIcon)
            self.tray_icon.setIcon(icon)
            
            # Criar menu do tray
            tray_menu = QMenu()
            
            # Ação: Abrir
            open_action = QAction("Abrir OrionTax Sync", self.app)
            open_action.triggered.connect(self.show_main_window)
            tray_menu.addAction(open_action)
            
            tray_menu.addSeparator()
            
            # Ação: Sair
            quit_action = QAction("Sair", self.app)
            quit_action.triggered.connect(self.quit_application)
            tray_menu.addAction(quit_action)
            
            self.tray_icon.setContextMenu(tray_menu)
            
            # Duplo clique abre a janela
            self.tray_icon.activated.connect(self.tray_icon_activated)
            
            # Mostrar tray icon
            self.tray_icon.show()
            
            logger.info("✓ System Tray inicializado")
            
        except Exception as e:
            logger.error(f"Erro ao inicializar tray: {e}")
    
    def tray_icon_activated(self, reason):
        """Chamado quando tray icon é clicado"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_main_window()
    
    def show_login(self):
        """Mostra tela de login INICIAL"""
        try:
            logger.info("Abrindo tela de login...")
            
            login_dialog = LoginDialog(db_manager=self.db_manager)
            
            if login_dialog.exec_() == login_dialog.Accepted:
                logger.info(f"✓ Login bem-sucedido: {login_dialog.username}")
                
                # ✅ ABRIR JANELA PRINCIPAL APÓS LOGIN INICIAL
                self.create_main_window()
            else:
                logger.info("Login cancelado")
                self.quit_application()
                
        except Exception as e:
            logger.error(f"Erro no login: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.quit_application()
    
    def create_main_window(self):
        """Cria e mostra janela principal"""
        try:
            logger.info("Criando janela principal...")
            
            # Criar nova janela com referência ao app para minimizar para tray
            self.main_window = MainWindow(self.db_manager, self.scheduler, self)
            self.main_window.show()
            
            # Mostrar notificação
            self.tray_icon.showMessage(
                "OrionTax Sync",
                "Sistema aberto. Minimize para continuar em segundo plano.",
                QSystemTrayIcon.Information,
                3000
            )
            
        except Exception as e:
            logger.error(f"Erro ao criar janela: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def show_main_window(self):
        """Mostra janela principal (PEDE LOGIN ANTES)"""
        try:
            logger.info("Solicitação para abrir janela...")
            
            # ✅ SEMPRE PEDIR LOGIN ANTES DE MOSTRAR JANELA
            login_dialog = LoginDialog(db_manager=self.db_manager)
            
            if login_dialog.exec_() != login_dialog.Accepted:
                logger.info("Login cancelado")
                return  # Login cancelado
            
            logger.info(f"✓ Login bem-sucedido: {login_dialog.username}")
            
            # Se já existe janela, apenas mostrar
            if self.main_window:
                self.main_window.show()
                self.main_window.raise_()
                self.main_window.activateWindow()
            else:
                # Criar nova janela
                self.create_main_window()
            
        except Exception as e:
            logger.error(f"Erro ao abrir janela: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def minimize_to_tray(self):
        """Minimiza janela para tray"""
        if self.main_window:
            self.main_window.hide()
            
            self.tray_icon.showMessage(
                "OrionTax Sync",
                "Sistema minimizado. Clique no ícone para reabrir.",
                QSystemTrayIcon.Information,
                2000
            )
            
            logger.info("Janela minimizada para tray")
    
    def quit_application(self):
        """Encerra aplicação"""
        try:
            logger.info("Encerrando aplicação...")
            
            # Parar scheduler
            if self.scheduler:
                self.scheduler.stop()
            
            # Fechar banco
            if self.db_manager:
                self.db_manager.disconnect()
            
            # Ocultar tray icon
            if self.tray_icon:
                self.tray_icon.hide()
            
            # Fechar janela se existir
            if self.main_window:
                self.main_window.close()
            
            # Fechar aplicação
            self.app.quit()
            
        except Exception as e:
            logger.error(f"Erro ao encerrar: {e}")
            sys.exit(1)
    
    def run(self):
        """Executa aplicação"""
        return self.app.exec_()


def main():
    """Função principal"""
    app = OrionTaxSyncApp()
    sys.exit(app.run())


if __name__ == '__main__':
    main()