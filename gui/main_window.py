"""
Janela Principal do Sistema OrionTax Sync
"""
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QTextEdit, QGroupBox,
                             QMessageBox, QStatusBar, QProgressBar, QTabWidget,
                             QTableWidget, QTableWidgetItem, QHeaderView,
                             QAction, QMenu, QMenuBar, QComboBox, QDialog)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon, QFont, QColor
from datetime import datetime, timezone
import threading
import traceback
import logging

# from config.database import db_manager
from gui.settings import (OracleConfigDialog, OrionTaxConfigDialog, HeartbeatConfigDialog,
                          SysmoConfigDialog, OrionTaxApiConfigDialog)
from gui.settings import UpdateConfigDialog
from core.integrations.profiles import get_erp_profile
from version import APP_VERSION


class UpdateCheckThread(QThread):
    finished = pyqtSignal(bool, object)

    def __init__(self, manifest_url, download=False, parent=None):
        super().__init__(parent)
        self.manifest_url = manifest_url
        self.download = download

    def run(self):
        try:
            from core.updater import UpdateChecker
            checker = UpdateChecker(self.manifest_url, APP_VERSION)
            info = checker.check()
            self.finished.emit(True, (info, checker.download(info) if info and self.download else None))
        except Exception as exc:
            self.finished.emit(False, str(exc))
from gui.client_dialog import ClientDialog
from gui.schedule import ScheduleDialog


class WorkerThread(QThread):
    """Thread para executar operações em background"""

    finished = pyqtSignal(bool, str, dict)  # success, message, stats
    progress = pyqtSignal(str)  # message

    def __init__(self, operation_type: str, oracle_config: dict, oriontax_config: dict,
                 cnpj: str, parent=None, db_manager=None, erp_type='intersolid'):
        super().__init__(parent)
        self.operation_type = operation_type  # 'ENVIAR' ou 'BUSCAR'
        self.oracle_config = oracle_config
        self.oriontax_config = oriontax_config
        self.cnpj = cnpj
        self.db_manager = db_manager
        self.erp_type = erp_type
        self._active_client = None  # cliente (Oracle/Firebird/OrionTax) conectado no momento
        self._client_lock = threading.Lock()
        self._cancel_requested = False

    def _set_active_client(self, client):
        """Registra qual cliente está com uma conexão aberta agora, para permitir cancelamento."""
        with self._client_lock:
            self._active_client = client

    def request_cancel(self):
        """
        Solicita o cancelamento da operação em andamento.
        Chamado pela thread da GUI enquanto esta thread pode estar bloqueada
        dentro de uma chamada de rede/banco (ex.: INSERT travado no Oracle).
        """
        self._cancel_requested = True
        with self._client_lock:
            client = self._active_client
        if client is not None:
            client.cancel()

    def run(self):
        """Executa a operação"""
        from datetime import datetime
        from core.oracle_client import create_db_client
        from core.oriontax_client import OrionTaxClient

        try:
            start_time = datetime.now()

            if self.erp_type == 'sysmo':
                from core.integrations import create_integration
                integration = create_integration(self.db_manager, 'sysmo')
                self._set_active_client(integration)
                result = (integration.send if self.operation_type == 'ENVIAR' else integration.receive)(
                    self.cnpj, self.progress.emit
                )
                stats = {'registros': result.records,
                         'tempo': (datetime.now() - start_time).total_seconds(),
                         'jobs': result.accepted_jobs}
                self.finished.emit(result.success, result.message, stats)
                return

            if self.operation_type == 'ENVIAR':
                # ENVIAR: BD Intersolid VIEWs → PostgreSQL VIEWs

                self.progress.emit('Conectando ao BD Intersolid...')
                oracle_client = create_db_client(self.oracle_config)
                self._set_active_client(oracle_client)
                oracle_client.connect()

                self.progress.emit(f'Lendo VIEWs do BD Intersolid (CNPJ: {self.cnpj})...')
                dataframes = oracle_client.read_views_to_dataframes()

                total_records = sum(len(df) for df in dataframes.values())
                self.progress.emit(f'✓ {total_records} registros lidos do BD Intersolid')

                oracle_client.disconnect()
                self._set_active_client(None)

                self.progress.emit('Conectando ao OrionTax...')
                oriontax_client = OrionTaxClient(self.oriontax_config)
                self._set_active_client(oriontax_client)
                oriontax_client.connect()

                self.progress.emit('Enviando dados para OrionTax...')
                success, message = oriontax_client.write_dataframes_to_views(self.cnpj, dataframes)

                oriontax_client.disconnect()
                self._set_active_client(None)

                stats = {
                    'registros': total_records,
                    'tempo': (datetime.now() - start_time).total_seconds()
                }

                self.finished.emit(True, f'✓ Dados enviados com sucesso!\n{message}', stats)

            elif self.operation_type == 'BUSCAR':
                # BUSCAR: PostgreSQL TMPs → Oracle TMPs

                self.progress.emit('Conectando ao OrionTax...')
                oriontax_client = OrionTaxClient(self.oriontax_config)
                self._set_active_client(oriontax_client)
                oriontax_client.connect()

                self.progress.emit(f'Lendo tabelas TMP do OrionTax (CNPJ: {self.cnpj})...')
                dataframes = oriontax_client.read_tmp_tables_to_dataframes(self.cnpj)

                total_records = sum(len(df) for df in dataframes.values())
                self.progress.emit(f'✓ {total_records} registros lidos do OrionTax')

                oriontax_client.disconnect()
                self._set_active_client(None)

                self.progress.emit('Conectando ao BD Intersolid...')
                oracle_client = create_db_client(self.oracle_config)
                self._set_active_client(oracle_client)
                oracle_client.connect()

                self.progress.emit('Gravando dados no BD Intersolid...')
                success, message = oracle_client.write_dataframes_to_tmp_tables(
                    dataframes, progress_callback=self.progress.emit
                )

                oracle_client.disconnect()
                self._set_active_client(None)

                stats = {
                    'registros': total_records,
                    'tempo': (datetime.now() - start_time).total_seconds()
                }

                self.finished.emit(True, f'✓ Dados recebidos com sucesso!\n{message}', stats)

        except Exception as e:
            import traceback
            if self._cancel_requested:
                error_msg = 'Operação cancelada pelo usuário.'
            else:
                error_msg = f'Erro: {str(e)}\n\n{traceback.format_exc()}'
            self.finished.emit(False, error_msg, {})
        finally:
            self._set_active_client(None)


class MainWindow(QMainWindow):
    """Janela Principal do Sistema"""
    
    def __init__(self, db_manager, scheduler, app_instance):
        """
        Inicializa a janela principal
        
        Args:
            db_manager: Instância do DatabaseManager
            scheduler: Instância do Scheduler
            app_instance: Instância do OrionTaxSyncApp (para minimizar)
        """
        super().__init__()
        
        self.db_manager = db_manager  # ✅ Armazenar db_manager
        self.scheduler = scheduler  # ✅ Armazenar scheduler
        self.app_instance = app_instance  # ✅ Armazenar app_instance
        self.logger = logging.getLogger(__name__)
        self.worker_thread = None
        self.erp_type = self.db_manager.get_installation()['erp_type']
        self.erp_profile = get_erp_profile(self.erp_type)
        
        # ✅ Buscar dados do usuário logado (opcional, se precisar)
        self.user_data = {'username': 'admin', 'nome_completo': 'Administrador'}
        
        self.init_ui()
        self.load_initial_data()
        self.setup_status_timer()
        self.setup_update_timer()
    
    def init_ui(self):
        """Inicializa a interface"""
        self.setWindowTitle(f'OrionTax Sync 2.0 - {self.erp_profile["name"]}')
        self.setGeometry(100, 100, 1200, 700)
        
        # Menu Bar
        self.create_menu_bar()
        
        # Widget Central
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Layout Principal
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Cabeçalho
        header_layout = self.create_header()
        main_layout.addLayout(header_layout)
        
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self.create_operations_tab(), '📊 Operações')
        self.tabs.addTab(self.create_config_tab(), '⚙️ Configurações')
        self.tabs.addTab(self.create_logs_tab(), '📋 Logs')
        self.tabs.addTab(self.create_schedule_tab(), '⏰ Agendamentos')
        main_layout.addWidget(self.tabs)
        
        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)
        
        self.status_label = QLabel('Pronto')
        self.status_bar.addWidget(self.status_label)
        
        central_widget.setLayout(main_layout)
        # self.apply_styles()
    
    def create_menu_bar(self):
        """Cria barra de menu"""
        menubar = self.menuBar()
        
        # Menu Arquivo
        file_menu = menubar.addMenu('Arquivo')
        
        exit_action = QAction('Sair', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        erp_menu = menubar.addMenu('ERP')
        intersolid_action = QAction('Usar Intersolid', self)
        intersolid_action.triggered.connect(lambda: self.change_erp_profile('intersolid'))
        erp_menu.addAction(intersolid_action)
        sysmo_action = QAction('Usar Sysmo', self)
        sysmo_action.triggered.connect(lambda: self.change_erp_profile('sysmo'))
        erp_menu.addAction(sysmo_action)
        
        # Menu Ajuda
        help_menu = menubar.addMenu('Ajuda')
        
        about_action = QAction('Sobre', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        update_action = QAction('Verificar atualizações', self)
        update_action.triggered.connect(self.check_for_updates)
        help_menu.addAction(update_action)
        update_config_action = QAction('Configurar canal de atualização', self)
        update_config_action.triggered.connect(lambda: UpdateConfigDialog(self).exec_())
        help_menu.addAction(update_config_action)

    def change_erp_profile(self, erp_type: str):
        """Altera explicitamente o perfil desta instalação e solicita reinício."""
        if erp_type == self.erp_type:
            QMessageBox.information(self, 'Perfil ERP', 'Este perfil já está ativo.')
            return
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, 'Operação em andamento', 'Cancele ou conclua a sincronização antes de trocar o ERP.')
            return
        name = get_erp_profile(erp_type)['name']
        reply = QMessageBox.question(
            self, 'Alterar perfil ERP',
            f'Alterar esta instalação para {name}?\n\nOs agendamentos serão preservados, mas revise-os antes de reativar a operação.',
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.db_manager.set_erp_type(erp_type)
            QMessageBox.information(self, 'Perfil alterado', 'Perfil salvo. Reinicie o OrionTax Sync para aplicar a nova interface.')

    def setup_update_timer(self):
        """Verifica releases sem bloquear a abertura e repete a cada 12 horas."""
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(lambda: self.check_for_updates(silent=True))
        self.update_timer.start(12 * 60 * 60 * 1000)
        QTimer.singleShot(5000, lambda: self.check_for_updates(silent=True))

    def check_for_updates(self, silent=False):
        manifest_url = self.db_manager.get_configuracao('update_manifest_url', '')
        if not manifest_url:
            if not silent:
                QMessageBox.information(
                    self, 'Atualizações',
                    'O canal de atualização ainda não foi configurado.\n\n'
                    'Defina update_manifest_url nas configurações da instalação.'
                )
            return
        if getattr(self, 'update_thread', None) and self.update_thread.isRunning():
            return
        self._update_check_silent = bool(silent)
        if not silent:
            self.status_label.setText('Verificando atualizações...')
        self.update_thread = UpdateCheckThread(manifest_url, parent=self)
        self.update_thread.finished.connect(self.on_update_checked)
        self.update_thread.start()

    def on_update_checked(self, success, result):
        if not success:
            self.logger.warning(f'Falha ao verificar atualização: {result}')
            if not getattr(self, '_update_check_silent', False):
                QMessageBox.warning(self, 'Atualizações', f'Não foi possível verificar atualizações:\n\n{result}')
            return
        info, _ = result
        if info is None:
            if not getattr(self, '_update_check_silent', False):
                QMessageBox.information(self, 'Atualizações', f'Você já utiliza a versão mais recente ({APP_VERSION}).')
            return
        reply = QMessageBox.question(
            self, 'Atualização disponível',
            f'Versão {info.version} disponível.\n\n{info.release_notes}\n\nBaixar e instalar agora?',
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            from core.integrations.lock import SyncLockRegistry
            if SyncLockRegistry.is_active() or (self.worker_thread and self.worker_thread.isRunning()):
                QMessageBox.warning(self, 'Atualização', 'Aguarde a sincronização em andamento terminar.')
                return
            self.status_label.setText('Baixando atualização...')
            self.update_thread = UpdateCheckThread(
                self.db_manager.get_configuracao('update_manifest_url', ''), download=True, parent=self
            )
            self.update_thread.finished.connect(self.on_update_downloaded)
            self.update_thread.start()

    def on_update_downloaded(self, success, result):
        if not success:
            QMessageBox.critical(self, 'Atualização', f'Falha ao baixar atualização:\n\n{result}')
            return
        info, installer = result
        try:
            from core.updater.launcher import launch_installer
            launch_installer(installer)
            self.app_instance.quit_application()
        except Exception as exc:
            QMessageBox.critical(self, 'Atualização', f'Não foi possível iniciar o instalador:\n\n{exc}')
    
    def create_header(self) -> QHBoxLayout:
        """Cria cabeçalho"""
        layout = QHBoxLayout()
        
        # Título
        title = QLabel(f'OrionTax Sync 2.0 — {self.erp_profile["name"]}')
        title_font = QFont('Arial', 18, QFont.Bold)
        title.setFont(title_font)
        # title.setStyleSheet('color: #2c3e50;')
        layout.addWidget(title)
        
        layout.addStretch()
        
        # ✅ Info do usuário (CLICÁVEL)
        from PyQt5.QtCore import Qt
        
        self.user_button = QPushButton(f"👤 {self.user_data.get('nome_completo', self.user_data['username'])}")
        self.user_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #3498db;
                border: none;
                font-size: 13px;
                text-decoration: underline;
                padding: 5px;
            }
            QPushButton:hover {
                color: #2980b9;
            }
        """)
        self.user_button.setCursor(Qt.PointingHandCursor)
        self.user_button.clicked.connect(self.open_change_password)
        layout.addWidget(self.user_button)
        
        return layout
    
    def open_change_password(self):
        """Abre diálogo de alteração de senha"""
        from gui.change_password import ChangePasswordDialog
        
        dialog = ChangePasswordDialog(
            db_manager=self.db_manager,
            username=self.user_data['username'],
            parent=self
        )
        
        if dialog.exec_():
            self.log_message('Senha alterada com sucesso', 'SUCCESS')
    
    def create_operations_tab(self) -> QWidget:
        """Cria aba de operações"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(15)
        
        # Seleção de Cliente
        client_group = QGroupBox('Selecionar Cliente')
        client_layout = QHBoxLayout()
        
        client_layout.addWidget(QLabel('Cliente:'))
        
        self.client_combo = QComboBox()
        self.client_combo.setMinimumWidth(300)
        client_layout.addWidget(self.client_combo)
        
        refresh_clients_button = QPushButton('🔄 Atualizar')
        refresh_clients_button.clicked.connect(self.load_clients)
        client_layout.addWidget(refresh_clients_button)
        
        client_layout.addStretch()
        
        client_group.setLayout(client_layout)
        layout.addWidget(client_group)

        # Limpeza de Tabelas Temporárias (BD Intersolid)
        clear_tmp_group = QGroupBox('Tabelas Temporárias (BD Intersolid)')
        clear_tmp_layout = QHBoxLayout()

        clear_icms_button = QPushButton('Limpar Tabela Temporária de ICMS')
        clear_icms_button.setCursor(Qt.PointingHandCursor)
        clear_icms_button.clicked.connect(lambda: self.clear_tmp_table('icms'))
        clear_tmp_layout.addWidget(clear_icms_button)

        clear_pis_cofins_button = QPushButton('Limpar Tabela Temporária do PIS/COFINS')
        clear_pis_cofins_button.setCursor(Qt.PointingHandCursor)
        clear_pis_cofins_button.clicked.connect(lambda: self.clear_tmp_table('pis_cofins'))
        clear_tmp_layout.addWidget(clear_pis_cofins_button)

        clear_ibs_cbs_button = QPushButton('Limpar Tabela Temporária do IBS/CBS')
        clear_ibs_cbs_button.setCursor(Qt.PointingHandCursor)
        clear_ibs_cbs_button.clicked.connect(lambda: self.clear_tmp_table('ibs_cbs'))
        clear_tmp_layout.addWidget(clear_ibs_cbs_button)

        clear_tmp_group.setLayout(clear_tmp_layout)
        clear_tmp_group.setVisible(self.erp_profile['show_tmp_cleanup'])
        layout.addWidget(clear_tmp_group)

        # Status das Conexões
        status_group = QGroupBox('Status das Conexões')
        status_layout = QVBoxLayout()
        
        self.oracle_status_label = QLabel(f'{self.erp_profile["erp_connection"]}: Não configurado')
        self.oriontax_status_label = QLabel(f'{self.erp_profile["oriontax_connection"]}: Não configurado')
        
        status_layout.addWidget(self.oracle_status_label)
        status_layout.addWidget(self.oriontax_status_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Botões de Operação
        operations_group = QGroupBox('Operações Manuais')
        operations_layout = QHBoxLayout()
        
        self.send_button = QPushButton(self.erp_profile['send_label'])
        self.send_button.setMinimumHeight(60)
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.clicked.connect(lambda: self.execute_operation('ENVIAR'))
        operations_layout.addWidget(self.send_button)
        
        self.receive_button = QPushButton(self.erp_profile['receive_label'])
        self.receive_button.setMinimumHeight(60)
        self.receive_button.setCursor(Qt.PointingHandCursor)
        self.receive_button.clicked.connect(lambda: self.execute_operation('BUSCAR'))
        operations_layout.addWidget(self.receive_button)

        self.cancel_button = QPushButton('🛑 Cancelar Execução')
        self.cancel_button.setMinimumHeight(60)
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setStyleSheet("""
            QPushButton { background-color: #e74c3c; color: white; font-weight: bold; border-radius: 5px; }
            QPushButton:hover:enabled { background-color: #c0392b; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        self.cancel_button.clicked.connect(self.cancel_current_operation)
        operations_layout.addWidget(self.cancel_button)

        operations_group.setLayout(operations_layout)
        layout.addWidget(operations_group)
        
        # Console de Saída
        console_group = QGroupBox('Console de Saída')
        console_layout = QVBoxLayout()
        
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(250)
        self.console.setStyleSheet("""
            QTextEdit {
                background-color: #2c3e50;
                color: #ecf0f1;
                font-family: 'Courier New', monospace;
                font-size: 11px;
                padding: 10px;
            }
        """)
        console_layout.addWidget(self.console)
        
        # Botão limpar console
        clear_button = QPushButton('Limpar Console')
        clear_button.clicked.connect(self.console.clear)
        console_layout.addWidget(clear_button)
        
        console_group.setLayout(console_layout)
        layout.addWidget(console_group)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def create_config_tab(self) -> QWidget:
        """Cria aba de configurações"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(20)
        
        # ========================================
        # CONFIGURAÇÃO ORACLE
        # ========================================
        oracle_group = QGroupBox('Configuração BD Intersolid')
        oracle_layout = QVBoxLayout()
        
        # Status Oracle
        self.oracle_config_status = QLabel('Status: Não configurado')
        self.oracle_config_status.setStyleSheet('font-weight: bold;')
        oracle_layout.addWidget(self.oracle_config_status)
        
        # Botões Oracle
        oracle_buttons = QHBoxLayout()
        
        config_oracle_button = QPushButton('⚙️ Configurar BD Intersolid')
        config_oracle_button.setMinimumHeight(40)
        config_oracle_button.clicked.connect(self.open_oracle_config)
        oracle_buttons.addWidget(config_oracle_button)
        
        test_oracle_button = QPushButton('🔍 Testar Conexão com Intersolid')
        test_oracle_button.setMinimumHeight(40)
        test_oracle_button.clicked.connect(self.test_oracle_connection)
        oracle_buttons.addWidget(test_oracle_button)
        
        oracle_layout.addLayout(oracle_buttons)
        oracle_group.setLayout(oracle_layout)
        layout.addWidget(oracle_group)
        oracle_group.setVisible(self.erp_type == 'intersolid')
        
        # ========================================
        # CONFIGURAÇÃO ORIONTAX
        # ========================================
        oriontax_group = QGroupBox('Configuração OrionTax (PostgreSQL)')
        oriontax_layout = QVBoxLayout()
        
        # Status OrionTax
        self.oriontax_config_status = QLabel('Status: Não configurado')
        self.oriontax_config_status.setStyleSheet('font-weight: bold;')
        oriontax_layout.addWidget(self.oriontax_config_status)
        
        # Botões OrionTax
        oriontax_buttons = QHBoxLayout()
        
        config_oriontax_button = QPushButton('⚙️ Configurar OrionTax')
        config_oriontax_button.setMinimumHeight(40)
        config_oriontax_button.clicked.connect(self.open_oriontax_config)
        oriontax_buttons.addWidget(config_oriontax_button)
        
        test_oriontax_button = QPushButton('🔍 Testar Conexão OrionTax')
        test_oriontax_button.setMinimumHeight(40)
        test_oriontax_button.clicked.connect(self.test_oriontax_connection)
        oriontax_buttons.addWidget(test_oriontax_button)
        
        oriontax_layout.addLayout(oriontax_buttons)
        oriontax_group.setLayout(oriontax_layout)
        layout.addWidget(oriontax_group)
        oriontax_group.setVisible(self.erp_type == 'intersolid')

        if self.erp_type == 'sysmo':
            sysmo_group = QGroupBox('Configuração Sysmo e API OrionTax')
            sysmo_layout = QHBoxLayout()
            sysmo_button = QPushButton('⚙️ Configurar PostgreSQL Sysmo')
            sysmo_button.clicked.connect(self.open_sysmo_config)
            api_button = QPushButton('⚙️ Configurar API OrionTax')
            api_button.clicked.connect(self.open_oriontax_api_config)
            sysmo_layout.addWidget(sysmo_button); sysmo_layout.addWidget(api_button)
            sysmo_group.setLayout(sysmo_layout); layout.addWidget(sysmo_group)

        # ========================================
        # HEARTBEAT
        # ========================================
        heartbeat_group = QGroupBox('Heartbeat (Monitoramento de Saúde)')
        heartbeat_layout = QVBoxLayout()

        interval = self.db_manager.get_heartbeat_interval()
        self.heartbeat_status_label = QLabel(f'Intervalo atual: {interval} minuto(s)')
        self.heartbeat_status_label.setStyleSheet('font-weight: bold;')
        heartbeat_layout.addWidget(self.heartbeat_status_label)

        heartbeat_buttons = QHBoxLayout()

        config_heartbeat_button = QPushButton('⚙️ Configurar Heartbeat')
        config_heartbeat_button.setMinimumHeight(40)
        config_heartbeat_button.clicked.connect(self.open_heartbeat_config)
        heartbeat_buttons.addWidget(config_heartbeat_button)

        heartbeat_layout.addLayout(heartbeat_buttons)
        heartbeat_group.setLayout(heartbeat_layout)
        layout.addWidget(heartbeat_group)

        # ========================================
        # GERENCIAMENTO DE CLIENTES
        # ========================================
        clients_group = QGroupBox('Gerenciamento de Clientes')
        clients_layout = QVBoxLayout()
        
        # Botões de ação
        clients_buttons = QHBoxLayout()
        
        add_client_button = QPushButton('➕ Adicionar Cliente')
        add_client_button.clicked.connect(self.add_client)
        clients_buttons.addWidget(add_client_button)
        
        edit_client_button = QPushButton('✏️ Editar Cliente')
        edit_client_button.clicked.connect(self.edit_client)
        clients_buttons.addWidget(edit_client_button)
        
        delete_client_button = QPushButton('🗑️ Excluir Cliente')
        delete_client_button.clicked.connect(self.delete_client)
        clients_buttons.addWidget(delete_client_button)
        
        clients_buttons.addStretch()
        
        refresh_button = QPushButton('🔄 Atualizar')
        refresh_button.clicked.connect(self.load_clients_table)
        clients_buttons.addWidget(refresh_button)
        
        clients_layout.addLayout(clients_buttons)
        
        # Tabela de clientes
        self.clients_table = QTableWidget()
        self.clients_table.setColumnCount(3)
        self.clients_table.setHorizontalHeaderLabels(['ID', 'Nome', 'CNPJ'])
        
        header = self.clients_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        
        self.clients_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.clients_table.setAlternatingRowColors(True)
        
        clients_layout.addWidget(self.clients_table)
        
        clients_group.setLayout(clients_layout)
        layout.addWidget(clients_group)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def create_logs_tab(self) -> QWidget:
        """Cria aba de logs"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Botões
        buttons_layout = QHBoxLayout()
        
        refresh_button = QPushButton('🔄 Atualizar Logs')
        refresh_button.clicked.connect(self.load_logs)
        buttons_layout.addWidget(refresh_button)
        
        # ✅ ADICIONAR BOTÃO VER ARQUIVO DE LOG
        view_log_file_button = QPushButton('📄 Ver Arquivo de Log')
        view_log_file_button.clicked.connect(self.view_log_file)
        buttons_layout.addWidget(view_log_file_button)
        
        buttons_layout.addStretch()
        
        layout.addLayout(buttons_layout)
        
        # Tabela de logs
        self.logs_table = QTableWidget()
        self.logs_table.setColumnCount(6)
        self.logs_table.setHorizontalHeaderLabels([
            'Data/Hora', 'Operação', 'Status', 'Mensagem', 'Registros', 'Tempo (s)'
        ])
        
        # Ajustar colunas
        header = self.logs_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        
        self.logs_table.setAlternatingRowColors(True)
        self.logs_table.setSelectionBehavior(QTableWidget.SelectRows)
        
        layout.addWidget(self.logs_table)
        
        widget.setLayout(layout)
        return widget
    
    def view_log_file(self):
        """Abre janela para visualizar arquivo de log"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton
        from pathlib import Path
        import sys

        # Usa o mesmo base_dir que main.py para apontar ao log correto
        if getattr(sys, 'frozen', False):
            base_dir = Path(sys.executable).parent
        else:
            base_dir = Path(__file__).parent.parent

        log_dir = base_dir / 'logs'
        log_filename = log_dir / 'oriontax.log'

        if not log_filename.exists():
            QMessageBox.warning(self, "Aviso", "Arquivo de log não encontrado.")
            return
        
        # Criar diálogo
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Log: {log_filename.name}")
        dialog.setGeometry(100, 100, 900, 600)
        
        layout = QVBoxLayout()
        
        # TextEdit para mostrar log
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #2c3e50;
                color: #ecf0f1;
                font-family: 'Courier New', monospace;
                font-size: 11px;
                padding: 10px;
            }
        """)
        
        # Ler arquivo
        try:
            with open(log_filename, 'r', encoding='utf-8') as f:
                content = f.read()
                text_edit.setPlainText(content)
                
            # Scroll para o final
            scrollbar = text_edit.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            
        except Exception as e:
            text_edit.setPlainText(f"Erro ao ler arquivo: {e}")
        
        layout.addWidget(text_edit)
        
        # Botão fechar
        close_button = QPushButton("Fechar")
        close_button.clicked.connect(dialog.close)
        layout.addWidget(close_button)
        
        dialog.setLayout(layout)
        dialog.exec_()
    
    def create_schedule_tab(self) -> QWidget:
        """Cria aba de agendamentos"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Botões
        buttons_layout = QHBoxLayout()
        
        add_button = QPushButton('➕ Adicionar Agendamento')
        add_button.clicked.connect(self.add_schedule)
        buttons_layout.addWidget(add_button)
        
        # ✅ ADICIONAR BOTÃO EDITAR
        edit_button = QPushButton('✏️ Editar Agendamento')
        edit_button.clicked.connect(self.edit_schedule)
        buttons_layout.addWidget(edit_button)
        
        # ✅ ADICIONAR BOTÃO EXCLUIR
        delete_button = QPushButton('🗑️ Excluir Agendamento')
        delete_button.clicked.connect(self.delete_schedule)
        buttons_layout.addWidget(delete_button)        
        
        buttons_layout.addStretch()
        
        refresh_button = QPushButton('🔄 Atualizar')
        refresh_button.clicked.connect(self.load_schedules)
        buttons_layout.addWidget(refresh_button)
        
        layout.addLayout(buttons_layout)
        
        # Tabela de agendamentos
        self.schedule_table = QTableWidget()
        self.schedule_table.setColumnCount(6)  # ✅ Adicionar coluna ID
        self.schedule_table.setHorizontalHeaderLabels([
            'ID', 'Operação', 'Frequência', 'Dias', 'Horário', 'Status'  # ✅ Adicionar ID
        ])
        
        header = self.schedule_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # ID
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Operação
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Frequência
        header.setSectionResizeMode(3, QHeaderView.Stretch)  # Dias
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Horário
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Status
        
        self.schedule_table.setAlternatingRowColors(True)
        self.schedule_table.setSelectionBehavior(QTableWidget.SelectRows)
        
        # ✅ CONECTAR DUPLO CLIQUE
        self.schedule_table.doubleClicked.connect(self.edit_schedule)        
        
        layout.addWidget(self.schedule_table)
        
        widget.setLayout(layout)
        return widget
    
    def apply_styles(self):
        """Aplica estilos CSS"""
        self.setStyleSheet("""
            QDialog {
                background-color: #ecf0f1;
            }
            QLineEdit {
                padding: 10px 15px;
                border: 2px solid #bdc3c7;
                border-radius: 5px;
                background-color: white;
                color: #2c3e50;                    /* ✅ Texto preto */
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #3498db;
            }
            QLineEdit::placeholder {
                color: #95a5a6;                    /* ✅ Placeholder cinza claro */
            }
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #21618c;
            }
        """)



    
    def log_message(self, message: str, level: str = 'INFO'):
        """Adiciona mensagem ao console"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        color_map = {
            'INFO': '#3498db',
            'SUCCESS': '#27ae60',
            'WARNING': '#f39c12',
            'ERROR': '#e74c3c'
        }
        
        color = color_map.get(level, '#ecf0f1')
        
        html = f'<span style="color: #95a5a6;">[{timestamp}]</span> '
        html += f'<span style="color: {color}; font-weight: bold;">[{level}]</span> '
        html += f'<span style="color: #ecf0f1;">{message}</span>'
        
        self.console.append(html)
        
        # Auto-scroll
        scrollbar = self.console.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def load_initial_data(self):
        """Carrega dados iniciais"""
        self.check_connection_status()
        self.load_clients()
        self.load_clients_table()
        self.load_logs()
        self.load_schedules()
        self.log_message('Sistema iniciado', 'SUCCESS')

        # Atualiza logs automaticamente a cada 30s (agendamentos rodam em background)
        self._log_refresh_timer = QTimer(self)
        self._log_refresh_timer.timeout.connect(self.load_logs)
        self._log_refresh_timer.start(30_000)
    
    def check_connection_status(self):
        """Verifica status das conexões"""
        if self.erp_type == 'sysmo':
            sysmo_config = self.db_manager.get_sysmo_config()
            api_config = self.db_manager.get_oriontax_api_config()
            if sysmo_config:
                self.oracle_status_label.setText(
                    f"✓ Banco Sysmo: {sysmo_config['host']}:{sysmo_config['port']} / {sysmo_config['database_name']}"
                )
                self.oracle_status_label.setStyleSheet('color: #27ae60; font-weight: bold;')
            else:
                self.oracle_status_label.setText('✗ Banco Sysmo: Não configurado')
                self.oracle_status_label.setStyleSheet('color: #e74c3c; font-weight: bold;')
            if api_config:
                self.oriontax_status_label.setText(f"✓ API OrionTax: {api_config['base_url']}")
                self.oriontax_status_label.setStyleSheet('color: #27ae60; font-weight: bold;')
            else:
                self.oriontax_status_label.setText('✗ API OrionTax: Não configurada')
                self.oriontax_status_label.setStyleSheet('color: #e74c3c; font-weight: bold;')
            return

        # ✅ Oracle
        oracle_config = self.db_manager.get_oracle_config()  # ✅ Adicionar self.
        if oracle_config:
            self.oracle_status_label.setText(f"✓ BD Intersolid: {oracle_config['nome_conexao']} ({oracle_config['host']})")
            self.oracle_status_label.setStyleSheet('color: #27ae60; font-weight: bold;')
            
            self.oracle_config_status.setText(f"✓ Configurado: {oracle_config['nome_conexao']} - {oracle_config['host']}:{oracle_config['port']}")
            self.oracle_config_status.setStyleSheet('color: #27ae60; font-weight: bold;')
        else:
            self.oracle_status_label.setText('✗ BD Intersolid: Não configurado')
            self.oracle_status_label.setStyleSheet('color: #e74c3c; font-weight: bold;')
            
            self.oracle_config_status.setText('✗ Não configurado')
            self.oracle_config_status.setStyleSheet('color: #e74c3c; font-weight: bold;')
        
        # ✅ OrionTax
        oriontax_config = self.db_manager.get_oriontax_config()  # ✅ Adicionar self.
        if oriontax_config:
            self.oriontax_status_label.setText(f"✓ OrionTax: {oriontax_config['host']}:{oriontax_config['port']}")
            self.oriontax_status_label.setStyleSheet('color: #27ae60; font-weight: bold;')
            
            self.oriontax_config_status.setText(f"✓ Configurado: {oriontax_config['host']}:{oriontax_config['port']} / {oriontax_config['database_name']}")
            self.oriontax_config_status.setStyleSheet('color: #27ae60; font-weight: bold;')
        else:
            self.oriontax_status_label.setText('✗ OrionTax: Não configurado')
            self.oriontax_status_label.setStyleSheet('color: #e74c3c; font-weight: bold;')
            
            self.oriontax_config_status.setText('✗ Não configurado')
            self.oriontax_config_status.setStyleSheet('color: #e74c3c; font-weight: bold;')
    
    def load_clients(self):
        """Carrega clientes no combo"""
        self.client_combo.clear()
        
        clientes = self.db_manager.get_all_clientes()  # ✅ Adicionar self.
        
        if not clientes:
            self.client_combo.addItem('Nenhum cliente cadastrado', None)
            return
        
        for cliente in clientes:
            cnpj_formatado = self.db_manager.format_cnpj(cliente['cnpj'])  # ✅ Adicionar self.
            display_text = f"{cliente['nome']} - {cnpj_formatado}"
            self.client_combo.addItem(display_text, cliente)
    
    def load_clients_table(self):
        """Carrega clientes na tabela"""
        clientes = self.db_manager.get_all_clientes()  # ✅ Adicionar self.
        
        self.clients_table.setRowCount(len(clientes))
        
        for row, cliente in enumerate(clientes):
            # ID
            self.clients_table.setItem(row, 0, QTableWidgetItem(str(cliente['id'])))
            
            # Nome
            self.clients_table.setItem(row, 1, QTableWidgetItem(cliente['nome']))
            
            # CNPJ formatado
            cnpj_formatado = self.db_manager.format_cnpj(cliente['cnpj'])  # ✅ Adicionar self.
            self.clients_table.setItem(row, 2, QTableWidgetItem(cnpj_formatado))
    
    def delete_client(self):
        """Exclui cliente selecionado"""
        selected_rows = self.clients_table.selectedItems()
        
        if not selected_rows:
            QMessageBox.warning(self, 'Atenção', 'Selecione um cliente para excluir.')
            return
        
        row = self.clients_table.currentRow()
        cliente_id = int(self.clients_table.item(row, 0).text())
        cliente_nome = self.clients_table.item(row, 1).text()
        
        reply = QMessageBox.question(
            self,
            'Confirmar Exclusão',
            f'Deseja realmente excluir o cliente "{cliente_nome}"?',
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if self.db_manager.delete_cliente(cliente_id):  # ✅ Adicionar self.
                self.load_clients()
                self.load_clients_table()
                self.log_message('Cliente excluído', 'SUCCESS')
            else:
                QMessageBox.critical(self, 'Erro', 'Erro ao excluir cliente.')
    
    def add_client(self):
        """Adiciona novo cliente"""
        dialog = ClientDialog(parent=self)
        if dialog.exec_():
            self.load_clients()
            self.load_clients_table()
            self.log_message('Cliente adicionado', 'SUCCESS')
    
    def edit_client(self):
        """Edita cliente selecionado"""
        selected_rows = self.clients_table.selectedItems()
        
        if not selected_rows:
            QMessageBox.warning(self, 'Atenção', 'Selecione um cliente para editar.')
            return
        
        row = self.clients_table.currentRow()
        cliente_id = int(self.clients_table.item(row, 0).text())
        
        dialog = ClientDialog(cliente_id=cliente_id, parent=self)
        if dialog.exec_():
            self.load_clients()
            self.load_clients_table()
            self.log_message('Cliente atualizado', 'SUCCESS')
    
    def test_oracle_connection(self):
        """Testa conexão Oracle"""
        oracle_config = self.db_manager.get_oracle_config()  # ✅ Adicionar self.
        
        if not oracle_config:
            QMessageBox.warning(self, 'Atenção', 'Configure a conexão BD Intersolid primeiro.')
            return
        
        try:
            from core.oracle_client import create_db_client

            self.log_message('Testando conexão BD Intersolid...', 'INFO')

            oracle_client = create_db_client(oracle_config)
            success, message = oracle_client.test_connection()

            if success:
                QMessageBox.information(self, 'Sucesso', '✓ Conexão BD Intersolid bem-sucedida!')
                self.log_message('✓ Conexão BD Intersolid OK', 'SUCCESS')
            else:
                QMessageBox.critical(self, 'Erro', f'Falha na conexão BD Intersolid:\n\n{message}')
                self.log_message(f'✗ Erro BD Intersolid: {message}', 'ERROR')
                
        except Exception as e:
            QMessageBox.critical(self, 'Erro', f'Erro ao testar conexão:\n\n{str(e)}')
            self.log_message(f'✗ Erro: {str(e)}', 'ERROR')
    
    def clear_tmp_table(self, kind: str):
        """Limpa (DELETE) a(s) tabela(s) temporária(s) do BD Intersolid (Oracle/Firebird)."""
        tables_by_kind = {
            'icms': ('ICMS', ['MXF_TMP_ICMS_ENTRADA', 'MXF_TMP_ICMS_SAIDA']),
            'pis_cofins': ('PIS/COFINS', ['MXF_TMP_PIS_COFINS']),
            'ibs_cbs': ('IBS/CBS', ['MXF_TMP_CBS_IBS']),
        }
        label, table_names = tables_by_kind[kind]

        oracle_config = self.db_manager.get_oracle_config()
        if not oracle_config:
            QMessageBox.warning(self, 'Atenção', 'Configure a conexão BD Intersolid primeiro.')
            return

        reply = QMessageBox.question(
            self,
            'Confirmar Limpeza',
            f'Deseja limpar a tabela temporária de {label} no BD Intersolid?\n\n'
            f'Isso vai executar DELETE FROM em: {", ".join(table_names)}\n\n'
            'Esta ação não pode ser desfeita.',
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        try:
            from core.oracle_client import create_db_client

            self.log_message(f'Limpando tabela(s) temporária(s) de {label}...', 'INFO')

            db_client = create_db_client(oracle_config)
            success, message = db_client.clear_tmp_tables(table_names)

            if success:
                QMessageBox.information(self, 'Sucesso', f'✓ Tabela temporária de {label} limpa com sucesso!')
                self.log_message(message, 'SUCCESS')
            else:
                QMessageBox.critical(self, 'Erro', f'Falha ao limpar tabela temporária de {label}:\n\n{message}')
                self.log_message(f'✗ Erro ao limpar {label}: {message}', 'ERROR')

        except Exception as e:
            QMessageBox.critical(self, 'Erro', f'Erro ao limpar tabela temporária de {label}:\n\n{str(e)}')
            self.log_message(f'✗ Erro: {str(e)}', 'ERROR')

    def test_oriontax_connection(self):
        """Testa conexão OrionTax"""
        oriontax_config = self.db_manager.get_oriontax_config()  # ✅ Adicionar self.
        
        if not oriontax_config:
            QMessageBox.warning(self, 'Atenção', 'Configure a conexão OrionTax primeiro.')
            return
        
        try:
            from core.oriontax_client import OrionTaxClient
            
            self.log_message('Testando conexão OrionTax...', 'INFO')
            
            oriontax_client = OrionTaxClient(oriontax_config)
            success, message = oriontax_client.test_connection()
            
            if success:
                QMessageBox.information(self, 'Sucesso', '✓ Conexão OrionTax bem-sucedida!')
                self.log_message('✓ Conexão OrionTax OK', 'SUCCESS')
            else:
                QMessageBox.critical(self, 'Erro', f'Falha na conexão OrionTax:\n\n{message}')
                self.log_message(f'✗ Erro OrionTax: {message}', 'ERROR')
                
        except Exception as e:
            QMessageBox.critical(self, 'Erro', f'Erro ao testar conexão:\n\n{str(e)}')
            self.log_message(f'✗ Erro: {str(e)}', 'ERROR')
    
    def load_logs(self):
        """Carrega logs na tabela"""
        logs = self.db_manager.get_logs_recentes(100)  # ✅ Adicionar self.
        
        self.logs_table.setRowCount(len(logs))
        
        for row, log in enumerate(logs):
            # Data/Hora — SQLite armazena em UTC, converter para horário local
            dt_utc = datetime.fromisoformat(log['created_at']).replace(tzinfo=timezone.utc)
            dt_local = dt_utc.astimezone(tz=None)
            self.logs_table.setItem(row, 0, QTableWidgetItem(dt_local.strftime('%d/%m/%Y %H:%M:%S')))
            
            # Operação
            self.logs_table.setItem(row, 1, QTableWidgetItem(log['tipo_operacao']))
            
            # Status
            status_item = QTableWidgetItem(log['status'])
            if log['status'] == 'SUCESSO':
                status_item.setForeground(QColor('#27ae60'))
            elif log['status'] == 'ERRO':
                status_item.setForeground(QColor('#e74c3c'))
            else:
                status_item.setForeground(QColor('#f39c12'))
            status_item.setFont(QFont('Arial', 10, QFont.Bold))
            self.logs_table.setItem(row, 2, status_item)
            
            # Mensagem
            self.logs_table.setItem(row, 3, QTableWidgetItem(log['mensagem'] or ''))
            
            # Registros
            self.logs_table.setItem(row, 4, QTableWidgetItem(str(log['registros_processados'])))
            
            # Tempo
            tempo = log['tempo_execucao_segundos'] or 0
            self.logs_table.setItem(row, 5, QTableWidgetItem(f"{tempo:.2f}"))
    
    def load_schedules(self):
        """Carrega agendamentos na tabela"""
        schedules = self.db_manager.get_all_schedules()
        
        self.schedule_table.setRowCount(len(schedules))
        
        for row, schedule in enumerate(schedules):
            # ✅ ID (coluna 0 - oculta visualmente mas acessível)
            id_item = QTableWidgetItem(str(schedule['id']))
            self.schedule_table.setItem(row, 0, id_item)
            
            # Operação (coluna 1)
            self.schedule_table.setItem(row, 1, QTableWidgetItem(schedule['operation_type']))
            
            # Tipo (coluna 2)
            tipo_map = {
                'daily': 'Diário',
                'weekly': 'Semanal',
                'monthly': 'Mensal'
            }
            tipo_text = tipo_map.get(schedule['schedule_type'], schedule['schedule_type'])
            self.schedule_table.setItem(row, 2, QTableWidgetItem(tipo_text))
            
            # Dia (coluna 3)
            if schedule['schedule_day'] is not None:
                if schedule['schedule_type'] == 'weekly':
                    dias_map = {0: 'Seg', 1: 'Ter', 2: 'Qua', 3: 'Qui', 4: 'Sex', 5: 'Sáb', 6: 'Dom'}
                    dia_text = dias_map.get(schedule['schedule_day'], str(schedule['schedule_day']))
                else:
                    dia_text = f"Dia {schedule['schedule_day']}"
            else:
                dia_text = '-'
            self.schedule_table.setItem(row, 3, QTableWidgetItem(dia_text))
            
            # Horário (coluna 4)
            self.schedule_table.setItem(row, 4, QTableWidgetItem(schedule['schedule_time']))
            
            # Status (coluna 5)
            status_item = QTableWidgetItem('Ativo' if schedule['is_active'] else 'Inativo')
            status_item.setForeground(QColor('#27ae60' if schedule['is_active'] else '#e74c3c'))
            status_item.setFont(QFont('Arial', 10, QFont.Bold))
            self.schedule_table.setItem(row, 5, status_item)
            
    def add_schedule(self):
        """Adiciona novo agendamento"""
        dialog = ScheduleDialog(self, self.db_manager)
        
        if dialog.exec_() == QDialog.Accepted:
            schedule_id = dialog.schedule_id
            
            # Buscar agendamento e adicionar ao scheduler
            schedule = self.db_manager.get_schedule(schedule_id)
            
            if schedule:
                self.scheduler.add_job(schedule)
            
            self.load_schedules()
            self.log_message('Agendamento adicionado', 'SUCCESS')
            QMessageBox.information(self, "Sucesso", "Agendamento criado!")
    
    def edit_schedule(self):
        """Edita agendamento selecionado"""
        current_row = self.schedule_table.currentRow()
        
        if current_row < 0:
            QMessageBox.warning(self, "Aviso", "Selecione um agendamento para editar")
            return
        
        # ✅ Pegar ID da coluna 0
        schedule_id = int(self.schedule_table.item(current_row, 0).text())
        
        # Buscar dados do agendamento
        schedule = self.db_manager.get_schedule(schedule_id)
        
        if not schedule:
            QMessageBox.warning(self, "Erro", "Agendamento não encontrado")
            return
        
        # Abrir diálogo de edição
        dialog = ScheduleDialog(self, self.db_manager, schedule)
        
        if dialog.exec_() == QDialog.Accepted:
            # ✅ Buscar agendamento atualizado
            updated_schedule = self.db_manager.get_schedule(schedule_id)
            
            if updated_schedule:
                # ✅ ATUALIZAR SCHEDULER DINAMICAMENTE
                self.scheduler.update_job(updated_schedule)
            
            self.load_schedules()
            self.log_message('Agendamento atualizado', 'SUCCESS')
            QMessageBox.information(self, "Sucesso", "Agendamento atualizado!")
    
    def delete_schedule(self):
        """Remove agendamento selecionado"""
        current_row = self.schedule_table.currentRow()
        
        if current_row < 0:
            QMessageBox.warning(self, "Aviso", "Selecione um agendamento para remover")
            return
        
        # ✅ Pegar ID da coluna 0
        schedule_id = int(self.schedule_table.item(current_row, 0).text())
        
        # Pegar operação e horário para mostrar na confirmação
        operacao = self.schedule_table.item(current_row, 1).text()
        horario = self.schedule_table.item(current_row, 4).text()
        
        reply = QMessageBox.question(
            self,
            "Confirmar",
            f"Deseja realmente remover este agendamento?\n\n{operacao} às {horario}",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # ✅ REMOVER DO SCHEDULER
            self.scheduler.remove_job(schedule_id)
            
            # Remover do banco
            self.db_manager.delete_schedule(schedule_id)
            
            self.load_schedules()
            self.log_message('Agendamento removido', 'SUCCESS')
            QMessageBox.information(self, "Sucesso", "Agendamento removido!")          
    
    def setup_status_timer(self):
        """Configura timer para atualizar status"""
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(60000)  # A cada 1 minuto
    
    def update_status(self):
        """Atualiza status na barra"""
        now = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        self.status_label.setText(f'Última atualização: {now}')
    
    def execute_operation(self, operation_type: str):
        """Executa operação (enviar ou buscar)"""
        # Validar configurações
        if self.erp_type == 'sysmo':
            oracle_config = self.db_manager.get_sysmo_config()
            oriontax_config = self.db_manager.get_oriontax_api_config()
        else:
            oracle_config = self.db_manager.get_oracle_config()
            oriontax_config = self.db_manager.get_oriontax_config()
        
        if not oracle_config:
            QMessageBox.warning(
                self,
                'Configuração Pendente',
                f'Configure a conexão {self.erp_profile["erp_connection"]} antes de continuar.'
            )
            return
        
        if not oriontax_config:
            QMessageBox.warning(
                self,
                'Configuração Pendente',
                'Configure a conexão OrionTax antes de continuar.'
            )
            return
        
        # Validar cliente selecionado
        current_data = self.client_combo.currentData()
        
        if current_data is None:
            QMessageBox.warning(
                self,
                'Cliente Não Selecionado',
                'Selecione um cliente antes de executar a operação.'
            )
            return
        
        cliente = current_data
        cnpj = cliente['cnpj']
        
        # Confirmar operação
        op_text = 'enviar dados para' if operation_type == 'ENVIAR' else 'buscar dados da'
        cnpj_formatado = self.db_manager.format_cnpj(cnpj)  # ✅ Adicionar self.
        
        reply = QMessageBox.question(
            self,
            'Confirmar Operação',
            f'Deseja {op_text} OrionTax?\n\nCliente: {cliente["nome"]}\nCNPJ: {cnpj_formatado}',
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            return
        
        # Desabilitar botões
        self.send_button.setEnabled(False)
        self.receive_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        # Mostrar progress bar
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate

        # Log
        self.log_message(f'Iniciando operação: {operation_type} (CNPJ: {cnpj_formatado})', 'INFO')

        # Criar e iniciar thread
        self.worker_thread = WorkerThread(operation_type, oracle_config, oriontax_config, cnpj,
                                          db_manager=self.db_manager, erp_type=self.erp_type)
        self.worker_thread.progress.connect(self.on_worker_progress)
        self.worker_thread.finished.connect(self.on_worker_finished)
        self.worker_thread.start()

    def on_worker_progress(self, message: str):
        """Callback de progresso da thread"""
        level = 'WARNING' if message.startswith('⏳') else 'INFO'
        self.log_message(message, level)

    def cancel_current_operation(self):
        """Solicita o cancelamento da operação manual em andamento"""
        if not self.worker_thread or not self.worker_thread.isRunning():
            return

        reply = QMessageBox.question(
            self,
            'Cancelar Execução',
            'Deseja realmente cancelar a operação em andamento?\n\n'
            'A conexão atual será interrompida e a operação não será concluída.',
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        self.log_message('Cancelamento solicitado pelo usuário...', 'WARNING')
        self.cancel_button.setEnabled(False)
        self.worker_thread.request_cancel()

    def on_worker_finished(self, success: bool, message: str, stats: dict):
        """Callback de conclusão da thread"""
        # Reabilitar botões
        self.send_button.setEnabled(True)
        self.receive_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

        # Esconder progress bar
        self.progress_bar.setVisible(False)
        
        if success:
            self.log_message(message, 'SUCCESS')
            
            if stats:
                self.log_message(
                    f"Registros processados: {stats.get('registros', 0)}", 
                    'INFO'
                )
                self.log_message(
                    f"Tempo de execução: {stats.get('tempo', 0):.2f}s",
                    'INFO'
                )
            
            QMessageBox.information(self, 'Sucesso', message)
        else:
            self.log_message(message, 'ERROR')
            QMessageBox.critical(self, 'Erro', message)
        
        # Recarregar logs
        self.load_logs()
    
    def open_oracle_config(self):
        """Abre diálogo de configuração Oracle"""
        dialog = OracleConfigDialog(self)
        if dialog.exec_():
            self.check_connection_status()
            self.log_message('Configuração BD Intersolid atualizada', 'SUCCESS')
    
    def open_oriontax_config(self):
        """Abre diálogo de configuração OrionTax"""
        dialog = OrionTaxConfigDialog(self)
        if dialog.exec_():
            self.check_connection_status()
            self.log_message('Configuração OrionTax atualizada', 'SUCCESS')

    def open_sysmo_config(self):
        dialog = SysmoConfigDialog(self)
        if dialog.exec_():
            self.check_connection_status()
            self.log_message('Configuração Sysmo atualizada', 'SUCCESS')

    def open_oriontax_api_config(self):
        dialog = OrionTaxApiConfigDialog(self)
        if dialog.exec_():
            self.check_connection_status()
            self.log_message('Configuração API OrionTax atualizada', 'SUCCESS')

    def open_heartbeat_config(self):
        """Abre diálogo de configuração do Heartbeat"""
        dialog = HeartbeatConfigDialog(self, scheduler=self.scheduler)
        if dialog.exec_():
            interval = self.db_manager.get_heartbeat_interval()
            self.heartbeat_status_label.setText(f'Intervalo atual: {interval} minuto(s)')
            self.log_message(f'Heartbeat configurado: {interval} minuto(s)', 'SUCCESS')
    
    # def open_schedule_dialog(self):
    #     """Abre diálogo de agendamento"""
    #     dialog = ScheduleDialog(self, self.db_manager)  # ✅ Passar self.db_manager
        
    #     if dialog.exec_() == QDialog.Accepted:
    #         schedule_id = dialog.schedule_id
            
    #         # Buscar agendamento e adicionar ao scheduler
    #         schedule = self.db_manager.get_schedule(schedule_id)
            
    #         if schedule:
    #             self.scheduler.add_job(schedule)
            
    #         self.load_schedules()
    #         self.log_message('Agendamento adicionado', 'SUCCESS')
    
    def closeEvent(self, event):
        """
        ✅ Intercepta evento de fechar janela
        Minimiza para tray ao invés de fechar
        """
        event.ignore()  # Ignora o fechamento
        self.app_instance.minimize_to_tray()  # Minimiza para tray
    
    def show_about(self):
        """Mostra diálogo sobre"""
        from version import APP_VERSION
        QMessageBox.about(
            self,
            'Sobre OrionTax Sync',
            f'<h2>OrionTax Sync v{APP_VERSION}</h2>'
            '<p>Sistema de Sincronização Fiscal</p>'
            '<p>Desenvolvido para integração entre Oracle/Firebird e OrionTax</p>'
            '<br>'
            '<p><b>Recursos:</b></p>'
            '<ul>'
            '<li>Sincronização bidirecional de dados fiscais</li>'
            '<li>Gerenciamento de múltiplos clientes</li>'
            '<li>Agendamento automático de operações</li>'
            '<li>Heartbeat — monitoramento remoto de saúde do sistema</li>'
            '<li>Logs detalhados de execução com atualização automática</li>'
            '<li>Criptografia de senhas</li>'
            '<li>Teste de conexões</li>'
            '</ul>'
            '<br>'
            '<p><b>Data de lançamento:</b> 29/04/2026</p>'
            '<p>© 2025 OrionTax. Todos os direitos reservados.</p>'
        )
    
