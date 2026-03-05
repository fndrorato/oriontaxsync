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
from datetime import datetime
import traceback
import logging

# from config.database import db_manager
from gui.settings import OracleConfigDialog, OrionTaxConfigDialog
from gui.client_dialog import ClientDialog
from gui.schedule import ScheduleDialog


class WorkerThread(QThread):
    """Thread para executar operações em background"""
    
    finished = pyqtSignal(bool, str, dict)  # success, message, stats
    progress = pyqtSignal(str)  # message
    
    def __init__(self, operation_type: str, oracle_config: dict, oriontax_config: dict, cnpj: str, parent=None):
        super().__init__(parent)
        self.operation_type = operation_type  # 'ENVIAR' ou 'BUSCAR'
        self.oracle_config = oracle_config
        self.oriontax_config = oriontax_config
        self.cnpj = cnpj
    
    def run(self):
        """Executa a operação"""
        from datetime import datetime
        from core.oracle_client import create_db_client
        from core.oriontax_client import OrionTaxClient

        try:
            start_time = datetime.now()

            if self.operation_type == 'ENVIAR':
                # ENVIAR: BD Intersolid VIEWs → PostgreSQL VIEWs

                self.progress.emit('Conectando ao BD Intersolid...')
                oracle_client = create_db_client(self.oracle_config)
                oracle_client.connect()

                self.progress.emit(f'Lendo VIEWs do BD Intersolid (CNPJ: {self.cnpj})...')
                dataframes = oracle_client.read_views_to_dataframes()

                total_records = sum(len(df) for df in dataframes.values())
                self.progress.emit(f'✓ {total_records} registros lidos do BD Intersolid')

                oracle_client.disconnect()
                
                self.progress.emit('Conectando ao OrionTax...')
                oriontax_client = OrionTaxClient(self.oriontax_config)
                oriontax_client.connect()
                
                self.progress.emit('Enviando dados para OrionTax...')
                success, message = oriontax_client.write_dataframes_to_views(self.cnpj, dataframes)
                
                oriontax_client.disconnect()
                
                stats = {
                    'registros': total_records,
                    'tempo': (datetime.now() - start_time).total_seconds()
                }
                
                self.finished.emit(True, f'✓ Dados enviados com sucesso!\n{message}', stats)
                
            elif self.operation_type == 'BUSCAR':
                # BUSCAR: PostgreSQL TMPs → Oracle TMPs
                
                self.progress.emit('Conectando ao OrionTax...')
                oriontax_client = OrionTaxClient(self.oriontax_config)
                oriontax_client.connect()
                
                self.progress.emit(f'Lendo tabelas TMP do OrionTax (CNPJ: {self.cnpj})...')
                dataframes = oriontax_client.read_tmp_tables_to_dataframes(self.cnpj)
                
                total_records = sum(len(df) for df in dataframes.values())
                self.progress.emit(f'✓ {total_records} registros lidos do OrionTax')
                
                oriontax_client.disconnect()
                
                self.progress.emit('Conectando ao BD Intersolid...')
                oracle_client = create_db_client(self.oracle_config)
                oracle_client.connect()

                self.progress.emit('Gravando dados no BD Intersolid...')
                success, message = oracle_client.write_dataframes_to_tmp_tables(dataframes)
                
                oracle_client.disconnect()
                
                stats = {
                    'registros': total_records,
                    'tempo': (datetime.now() - start_time).total_seconds()
                }
                
                self.finished.emit(True, f'✓ Dados recebidos com sucesso!\n{message}', stats)
        
        except Exception as e:
            import traceback
            error_msg = f'Erro: {str(e)}\n\n{traceback.format_exc()}'
            self.finished.emit(False, error_msg, {})


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
        
        # ✅ Buscar dados do usuário logado (opcional, se precisar)
        self.user_data = {'username': 'admin', 'nome_completo': 'Administrador'}
        
        self.init_ui()
        self.load_initial_data()
        self.setup_status_timer()
    
    def init_ui(self):
        """Inicializa a interface"""
        self.setWindowTitle('OrionTax Sync - Sistema de Sincronização Fiscal')
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
        
        # Menu Ajuda
        help_menu = menubar.addMenu('Ajuda')
        
        about_action = QAction('Sobre', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def create_header(self) -> QHBoxLayout:
        """Cria cabeçalho"""
        layout = QHBoxLayout()
        
        # Título
        title = QLabel('OrionTax Sync')
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
        
        # Status das Conexões
        status_group = QGroupBox('Status das Conexões')
        status_layout = QVBoxLayout()
        
        self.oracle_status_label = QLabel('BD Intersolid: Não configurado')
        self.oriontax_status_label = QLabel('OrionTax: Não configurado')
        
        status_layout.addWidget(self.oracle_status_label)
        status_layout.addWidget(self.oriontax_status_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Botões de Operação
        operations_group = QGroupBox('Operações Manuais')
        operations_layout = QHBoxLayout()
        
        self.send_button = QPushButton('📤 Enviar Dados para OrionTax')
        self.send_button.setMinimumHeight(60)
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.clicked.connect(lambda: self.execute_operation('ENVIAR'))
        operations_layout.addWidget(self.send_button)
        
        self.receive_button = QPushButton('📥 Buscar Dados da OrionTax')
        self.receive_button.setMinimumHeight(60)
        self.receive_button.setCursor(Qt.PointingHandCursor)
        self.receive_button.clicked.connect(lambda: self.execute_operation('BUSCAR'))
        operations_layout.addWidget(self.receive_button)
        
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
        from datetime import datetime
        
        # Caminho do log de hoje
        log_dir = Path(__file__).parent.parent / 'logs'
        log_filename = log_dir / f'oriontax_{datetime.now().strftime("%Y%m%d")}.log'
        
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
    
    def check_connection_status(self):
        """Verifica status das conexões"""
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
            # Data/Hora
            dt = datetime.fromisoformat(log['created_at'])
            self.logs_table.setItem(row, 0, QTableWidgetItem(dt.strftime('%d/%m/%Y %H:%M:%S')))
            
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
        oracle_config = self.db_manager.get_oracle_config()
        oriontax_config = self.db_manager.get_oriontax_config() 
        
        if not oracle_config:
            QMessageBox.warning(
                self,
                'Configuração Pendente',
                'Configure a conexão BD Intersolid antes de continuar.'
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
        
        # Mostrar progress bar
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        
        # Log
        self.log_message(f'Iniciando operação: {operation_type} (CNPJ: {cnpj_formatado})', 'INFO')
        
        # Criar e iniciar thread
        self.worker_thread = WorkerThread(operation_type, oracle_config, oriontax_config, cnpj)
        self.worker_thread.progress.connect(self.on_worker_progress)
        self.worker_thread.finished.connect(self.on_worker_finished)
        self.worker_thread.start()
    
    def on_worker_progress(self, message: str):
        """Callback de progresso da thread"""
        self.log_message(message, 'INFO')
    
    def on_worker_finished(self, success: bool, message: str, stats: dict):
        """Callback de conclusão da thread"""
        # Reabilitar botões
        self.send_button.setEnabled(True)
        self.receive_button.setEnabled(True)
        
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
        QMessageBox.about(
            self,
            'Sobre OrionTax Sync',
            '<h2>OrionTax Sync v1.0.1</h2>'
            '<p>Sistema de Sincronização Fiscal</p>'
            '<p>Desenvolvido para integração entre Oracle e OrionTax</p>'
            '<br>'
            '<p><b>Recursos:</b></p>'
            '<ul>'
            '<li>Sincronização bidirecional de dados fiscais</li>'
            '<li>Gerenciamento de múltiplos clientes</li>'
            '<li>Agendamento automático de operações</li>'
            '<li>Logs detalhados de execução</li>'
            '<li>Criptografia de senhas</li>'
            '<li>Teste de conexões</li>'
            '</ul>'
            '<br>'
            '<p>© 2025 OrionTax. Todos os direitos reservados.</p>'
        )
    

