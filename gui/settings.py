"""
Diálogos de Configuração
"""
import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QSpinBox, QCheckBox,
                             QGroupBox, QFormLayout, QMessageBox, QComboBox,
                             QTimeEdit, QListWidget, QFileDialog, QWidget)
from PyQt5.QtCore import Qt, QTime
from PyQt5.QtGui import QFont
from config.database import db_manager
import json


class DatabaseConfigDialog(QDialog):
    """Diálogo de Configuração de Banco de Dados (Oracle ou Firebird)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.load_config()

    def init_ui(self):
        """Inicializa a interface"""
        self.setWindowTitle('Configuração Banco de Dados')
        self.setMinimumWidth(580)

        layout = QVBoxLayout()
        layout.setSpacing(15)

        group = QGroupBox('Dados de Conexão')
        form = QFormLayout()
        form.setSpacing(10)

        # Tipo de Banco de Dados
        self.db_type_combo = QComboBox()
        self.db_type_combo.addItems(['Oracle', 'Firebird 2.5'])
        self.db_type_combo.currentTextChanged.connect(self.on_db_type_changed)
        form.addRow('Tipo de Banco:', self.db_type_combo)

        # Nome da Conexão
        self.nome_input = QLineEdit()
        self.nome_input.setPlaceholderText('Ex: Producao, Homologacao')
        form.addRow('Nome da Conexão:', self.nome_input)

        # Host
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText('192.168.1.100 ou servidor.empresa.com')
        form.addRow('Host:', self.host_input)

        # Port
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(1521)
        form.addRow('Porta:', self.port_input)

        # Service Name (Oracle)
        self.service_input = QLineEdit()
        self.service_input.setPlaceholderText('ORCL, XE, etc')
        self.service_label = QLabel('Service Name:')
        form.addRow(self.service_label, self.service_input)

        # Database Path (Firebird)
        db_path_container = QWidget()
        db_path_layout = QHBoxLayout(db_path_container)
        db_path_layout.setContentsMargins(0, 0, 0, 0)
        self.db_path_input = QLineEdit()
        self.db_path_input.setPlaceholderText('/caminho/para/banco.fdb')
        browse_db_button = QPushButton('📁')
        browse_db_button.setMaximumWidth(40)
        browse_db_button.setToolTip('Procurar arquivo .fdb')
        browse_db_button.clicked.connect(self.browse_database_file)
        db_path_layout.addWidget(self.db_path_input)
        db_path_layout.addWidget(browse_db_button)
        self.db_path_label = QLabel('Database:')
        form.addRow(self.db_path_label, db_path_container)
        self.db_path_container = db_path_container

        # Charset (Firebird)
        self.charset_input = QLineEdit()
        self.charset_input.setPlaceholderText('WIN1252, UTF8, NONE (padrão: WIN1252)')
        self.charset_label = QLabel('Charset:')
        form.addRow(self.charset_label, self.charset_input)

        # Username
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText('usuario')
        form.addRow('Usuário:', self.username_input)

        # Password
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText('••••••••')
        form.addRow('Senha:', self.password_input)

        # Instant Client Path (Oracle)
        instant_client_container = QWidget()
        ic_outer = QVBoxLayout(instant_client_container)
        ic_outer.setContentsMargins(0, 0, 0, 0)

        instant_client_row = QHBoxLayout()
        self.instant_client_input = QLineEdit()
        self.instant_client_input.setPlaceholderText('/path/to/instantclient_19_20')
        instant_client_row.addWidget(self.instant_client_input)

        browse_ic_button = QPushButton('📁')
        browse_ic_button.setMaximumWidth(40)
        browse_ic_button.setToolTip('Procurar diretório')
        browse_ic_button.clicked.connect(self.browse_instant_client)
        instant_client_row.addWidget(browse_ic_button)
        ic_outer.addLayout(instant_client_row)

        instant_client_info = QLabel('Opcional: Para Oracle < 12.1 (modo thick). Deixe vazio para usar modo thin.')
        instant_client_info.setStyleSheet('color: #7f8c8d; font-size: 10px;')
        instant_client_info.setWordWrap(True)
        ic_outer.addWidget(instant_client_info)

        self.instant_client_label = QLabel('Instant Client:')
        form.addRow(self.instant_client_label, instant_client_container)
        self.instant_client_container = instant_client_container

        group.setLayout(form)
        layout.addWidget(group)

        # Botões
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        test_button = QPushButton('Testar Conexão')
        test_button.clicked.connect(self.test_connection)
        buttons_layout.addWidget(test_button)

        save_button = QPushButton('Salvar')
        save_button.clicked.connect(self.save_config)
        save_button.setDefault(True)
        buttons_layout.addWidget(save_button)

        cancel_button = QPushButton('Cancelar')
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)

        layout.addLayout(buttons_layout)
        self.setLayout(layout)

        self.apply_styles()

        # Inicializa visibilidade dos campos conforme tipo padrão
        self.on_db_type_changed('Oracle')

    def on_db_type_changed(self, db_type: str):
        """Mostra/oculta campos conforme o tipo de banco selecionado"""
        is_oracle = db_type == 'Oracle'
        is_firebird = db_type == 'Firebird 2.5'

        # Campos Oracle
        self.service_label.setVisible(is_oracle)
        self.service_input.setVisible(is_oracle)
        self.instant_client_label.setVisible(is_oracle)
        self.instant_client_container.setVisible(is_oracle)

        # Campos Firebird
        self.db_path_label.setVisible(is_firebird)
        self.db_path_container.setVisible(is_firebird)
        self.charset_label.setVisible(is_firebird)
        self.charset_input.setVisible(is_firebird)

        # Atualiza porta padrão apenas se ainda estiver no valor padrão do outro banco
        if is_oracle and self.port_input.value() == 3050:
            self.port_input.setValue(1521)
        elif is_firebird and self.port_input.value() == 1521:
            self.port_input.setValue(3050)

        # Atualiza placeholder do usuário
        if is_firebird:
            self.username_input.setPlaceholderText('SYSDBA')
        else:
            self.username_input.setPlaceholderText('usuario_oracle')

    def apply_styles(self):
        """Aplica estilos"""
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #bdc3c7;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLineEdit, QSpinBox, QComboBox {
                padding: 8px;
                border: 1px solid #bdc3c7;
                border-radius: 3px;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 2px solid #3498db;
            }
            QPushButton {
                padding: 8px 20px;
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 3px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)

    def browse_instant_client(self):
        """Abre diálogo para selecionar diretório do Instant Client"""
        directory = QFileDialog.getExistingDirectory(
            self,
            'Selecionar Diretório do Oracle Instant Client',
            os.path.expanduser('~'),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if directory:
            self.instant_client_input.setText(directory)

    def browse_database_file(self):
        """Abre diálogo para selecionar arquivo .fdb do Firebird"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            'Selecionar Banco de Dados Firebird',
            os.path.expanduser('~'),
            'Firebird Database (*.fdb *.gdb);;Todos os arquivos (*.*)'
        )
        if file_path:
            self.db_path_input.setText(file_path)

    def load_config(self):
        """Carrega configuração existente"""
        config = db_manager.get_oracle_config()
        if config:
            self.nome_input.setText(config.get('nome_conexao', ''))
            self.host_input.setText(config.get('host', ''))
            self.port_input.setValue(config.get('port', 1521))
            self.username_input.setText(config.get('username', ''))

            db_type = config.get('db_type', 'oracle')
            if db_type == 'firebird':
                self.db_type_combo.setCurrentText('Firebird 2.5')
                self.db_path_input.setText(config.get('database_path', '') or '')
                self.charset_input.setText(config.get('charset', '') or '')
            else:
                self.db_type_combo.setCurrentText('Oracle')
                self.service_input.setText(config.get('service_name', ''))
                self.instant_client_input.setText(config.get('instant_client_path', '') or '')
            # Senha não é carregada por segurança

    def validate_fields(self) -> bool:
        """Valida campos obrigatórios"""
        if not self.nome_input.text().strip():
            QMessageBox.warning(self, 'Atenção', 'Informe o nome da conexão.')
            self.nome_input.setFocus()
            return False

        if not self.host_input.text().strip():
            QMessageBox.warning(self, 'Atenção', 'Informe o host.')
            self.host_input.setFocus()
            return False

        is_firebird = self.db_type_combo.currentText() == 'Firebird 2.5'

        if is_firebird:
            if not self.db_path_input.text().strip():
                QMessageBox.warning(self, 'Atenção', 'Informe o caminho do banco de dados (.fdb).')
                self.db_path_input.setFocus()
                return False
        else:
            if not self.service_input.text().strip():
                QMessageBox.warning(self, 'Atenção', 'Informe o service name.')
                self.service_input.setFocus()
                return False

        if not self.username_input.text().strip():
            QMessageBox.warning(self, 'Atenção', 'Informe o usuário.')
            self.username_input.setFocus()
            return False

        if not self.password_input.text():
            QMessageBox.warning(self, 'Atenção', 'Informe a senha.')
            self.password_input.setFocus()
            return False

        return True

    def test_connection(self):
        """Testa conexão conforme o tipo de banco selecionado"""
        if not self.validate_fields():
            return

        if self.db_type_combo.currentText() == 'Firebird 2.5':
            self._test_firebird_connection()
        else:
            self._test_oracle_connection()

    def _test_oracle_connection(self):
        """Testa conexão Oracle"""
        try:
            from core.oracle_client import OracleClient

            temp_config = {
                'host': self.host_input.text().strip(),
                'port': self.port_input.value(),
                'service_name': self.service_input.text().strip(),
                'username': self.username_input.text().strip(),
                'password': self.password_input.text(),
                'instant_client_path': self.instant_client_input.text().strip() or None
            }

            oracle_client = OracleClient(temp_config)
            success, message = oracle_client.test_connection()

            if success:
                QMessageBox.information(self, 'Sucesso', f'✓ {message}')
            else:
                QMessageBox.critical(
                    self, 'Erro de Conexão',
                    f'Não foi possível conectar ao Oracle:\n\n{message}'
                )
        except Exception as e:
            QMessageBox.critical(
                self, 'Erro de Conexão',
                f'Não foi possível conectar ao Oracle:\n\n{str(e)}'
            )

    def _test_firebird_connection(self):
        """Testa conexão Firebird"""
        try:
            import firebirdsql
        except ImportError:
            QMessageBox.critical(
                self, 'Biblioteca não encontrada',
                'A biblioteca "firebirdsql" não está instalada.\n\nInstale com:\n  pip install firebirdsql'
            )
            return

        try:
            charset = self.charset_input.text().strip() or 'WIN1252'
            con = firebirdsql.connect(
                host=self.host_input.text().strip(),
                database=self.db_path_input.text().strip(),
                user=self.username_input.text().strip(),
                password=self.password_input.text(),
                port=self.port_input.value(),
                charset=charset,
                auth_plugin_name='Legacy_Auth',
            )
            con.close()
            QMessageBox.information(self, 'Sucesso', '✓ Conexão ao Firebird realizada com sucesso!')
        except Exception as e:
            QMessageBox.critical(
                self, 'Erro de Conexão',
                f'Não foi possível conectar ao Firebird:\n\n{str(e)}'
            )

    def save_config(self):
        """Salva configuração"""
        if not self.validate_fields():
            return

        is_firebird = self.db_type_combo.currentText() == 'Firebird 2.5'
        db_type = 'firebird' if is_firebird else 'oracle'

        if is_firebird:
            service_name = ''
            instant_client_path = None
            database_path = self.db_path_input.text().strip()
            charset = self.charset_input.text().strip() or 'WIN1252'
        else:
            service_name = self.service_input.text().strip()
            instant_client_path = self.instant_client_input.text().strip() or None
            database_path = None
            charset = None

        success = db_manager.save_oracle_config(
            nome_conexao=self.nome_input.text().strip(),
            host=self.host_input.text().strip(),
            port=self.port_input.value(),
            service_name=service_name,
            username=self.username_input.text().strip(),
            password=self.password_input.text(),
            instant_client_path=instant_client_path,
            db_type=db_type,
            database_path=database_path,
            charset=charset
        )

        if success:
            QMessageBox.information(self, 'Sucesso', 'Configuração salva com sucesso!')
            self.accept()
        else:
            QMessageBox.critical(self, 'Erro', 'Erro ao salvar configuração.')


# Alias para compatibilidade com código existente
OracleConfigDialog = DatabaseConfigDialog

class OrionTaxConfigDialog(QDialog):
    """Diálogo de Configuração OrionTax (PostgreSQL)"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.load_config()
    
    def init_ui(self):
        """Inicializa a interface"""
        self.setWindowTitle('Configuração OrionTax')
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        
        # GroupBox principal
        group = QGroupBox('Dados de Conexão OrionTax (PostgreSQL)')
        form = QFormLayout()
        form.setSpacing(10)
        
        # Host
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText('oriontax.servidor.com ou IP')
        form.addRow('Host:', self.host_input)
        
        # Port
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(5432)
        form.addRow('Porta:', self.port_input)
        
        # Database
        self.database_input = QLineEdit()
        self.database_input.setPlaceholderText('oriontax')
        form.addRow('Banco de Dados:', self.database_input)
        
        # Username
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText('oriontax_user')
        form.addRow('Usuário:', self.username_input)
        
        # Password
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText('••••••••')
        form.addRow('Senha:', self.password_input)
        
        # SSL
        self.ssl_checkbox = QCheckBox('Usar SSL/TLS')
        self.ssl_checkbox.setChecked(True)
        form.addRow('Segurança:', self.ssl_checkbox)
        
        group.setLayout(form)
        layout.addWidget(group)
        
        # Botões
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        test_button = QPushButton('Testar Conexão')
        test_button.clicked.connect(self.test_connection)
        buttons_layout.addWidget(test_button)
        
        save_button = QPushButton('Salvar')
        save_button.clicked.connect(self.save_config)
        save_button.setDefault(True)
        buttons_layout.addWidget(save_button)
        
        cancel_button = QPushButton('Cancelar')
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)
        
        layout.addLayout(buttons_layout)
        self.setLayout(layout)
        
        self.apply_styles()
    
    def apply_styles(self):
        """Aplica estilos"""
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #bdc3c7;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLineEdit, QSpinBox {
                padding: 8px;
                border: 1px solid #bdc3c7;
                border-radius: 3px;
            }
            QLineEdit:focus, QSpinBox:focus {
                border: 2px solid #3498db;
            }
            QPushButton {
                padding: 8px 20px;
                background-color: #27ae60;
                color: white;
                border: none;
                border-radius: 3px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #229954;
            }
        """)
    
    def load_config(self):
        """Carrega configuração existente"""
        config = db_manager.get_oriontax_config()
        if config:
            self.host_input.setText(config.get('host', ''))
            self.port_input.setValue(config.get('port', 5432))
            self.database_input.setText(config.get('database_name', ''))
            self.username_input.setText(config.get('username', ''))
            self.ssl_checkbox.setChecked(config.get('use_ssl', True))
    
    def test_connection(self):
        """Testa conexão PostgreSQL"""
        if not self.validate_fields():
            return
        
        try:
            import psycopg2
            
            sslmode = 'require' if self.ssl_checkbox.isChecked() else 'disable'
            
            connection = psycopg2.connect(
                host=self.host_input.text(),
                port=self.port_input.value(),
                database=self.database_input.text(),
                user=self.username_input.text(),
                password=self.password_input.text(),
                sslmode=sslmode,
                connect_timeout=10
            )
            
            connection.close()
            
            QMessageBox.information(
                self,
                'Sucesso',
                '✓ Conexão realizada com sucesso!'
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                'Erro de Conexão',
                f'Não foi possível conectar ao OrionTax:\n\n{str(e)}'
            )
    
    def validate_fields(self) -> bool:
        """Valida campos"""
        if not self.host_input.text().strip():
            QMessageBox.warning(self, 'Atenção', 'Informe o host.')
            self.host_input.setFocus()
            return False
        
        if not self.database_input.text().strip():
            QMessageBox.warning(self, 'Atenção', 'Informe o banco de dados.')
            self.database_input.setFocus()
            return False
        
        if not self.username_input.text().strip():
            QMessageBox.warning(self, 'Atenção', 'Informe o usuário.')
            self.username_input.setFocus()
            return False
        
        if not self.password_input.text():
            QMessageBox.warning(self, 'Atenção', 'Informe a senha.')
            self.password_input.setFocus()
            return False
        
        return True
    
    def save_config(self):
        """Salva configuração"""
        if not self.validate_fields():
            return
        
        success = db_manager.save_oriontax_config(
            host=self.host_input.text().strip(),
            port=self.port_input.value(),
            database_name=self.database_input.text().strip(),
            username=self.username_input.text().strip(),
            password=self.password_input.text(),
            use_ssl=self.ssl_checkbox.isChecked()
        )
        
        if success:
            QMessageBox.information(
                self,
                'Sucesso',
                'Configuração salva com sucesso!'
            )
            self.accept()
        else:
            QMessageBox.critical(
                self,
                'Erro',
                'Erro ao salvar configuração.'
            )


class HeartbeatConfigDialog(QDialog):
    """Diálogo de Configuração do Heartbeat"""

    def __init__(self, parent=None, scheduler=None):
        """
        Args:
            parent: Widget pai
            scheduler: Instância do Scheduler (para reiniciar o heartbeat ao salvar)
        """
        super().__init__(parent)
        self.scheduler = scheduler
        self.init_ui()
        self.load_config()

    def init_ui(self):
        self.setWindowTitle('Configuração do Heartbeat')
        self.setMinimumWidth(420)

        layout = QVBoxLayout()
        layout.setSpacing(15)

        group = QGroupBox('Monitoramento de Saúde (Heartbeat)')
        form = QFormLayout()
        form.setSpacing(12)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setValue(5)
        self.interval_spin.setSuffix(' minuto(s)')
        form.addRow('Intervalo de envio:', self.interval_spin)

        group.setLayout(form)
        layout.addWidget(group)

        info_label = QLabel(
            'O heartbeat envia métricas do sistema (CPU, memória, disco) '
            'ao servidor OrionTax a cada intervalo configurado.\n'
            'Mínimo: 1 minuto | Máximo: 1440 minutos (24 horas)'
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet('color: #7f8c8d; font-size: 11px;')
        layout.addWidget(info_label)

        buttons = QHBoxLayout()
        buttons.addStretch()

        save_btn = QPushButton('Salvar')
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.save_config)
        buttons.addWidget(save_btn)

        cancel_btn = QPushButton('Cancelar')
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)

        layout.addLayout(buttons)
        self.setLayout(layout)

        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #bdc3c7;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QSpinBox {
                padding: 8px;
                border: 1px solid #bdc3c7;
                border-radius: 3px;
            }
            QSpinBox:focus {
                border: 2px solid #3498db;
            }
            QPushButton {
                padding: 8px 20px;
                background-color: #27ae60;
                color: white;
                border: none;
                border-radius: 3px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #229954;
            }
        """)

    def load_config(self):
        interval = db_manager.get_heartbeat_interval()
        self.interval_spin.setValue(interval)

    def save_config(self):
        interval = self.interval_spin.value()

        if not db_manager.set_heartbeat_interval(interval):
            QMessageBox.critical(self, 'Erro', 'Não foi possível salvar a configuração.')
            return

        # Reinicia o heartbeat com o novo intervalo se o scheduler estiver disponível
        if self.scheduler:
            try:
                heartbeat_job = self.scheduler.scheduler.get_job('heartbeat')
                if heartbeat_job:
                    heartbeat_service = heartbeat_job.func.__self__
                    self.scheduler.start_heartbeat(heartbeat_service, interval)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f'Não foi possível reiniciar heartbeat: {e}')

        QMessageBox.information(
            self,
            'Sucesso',
            f'Heartbeat configurado para enviar a cada {interval} minuto(s).'
        )
        self.accept()


# class ScheduleDialog(QDialog):
#     """Diálogo de Agendamento"""

#     DIAS_SEMANA = {
#         0: 'Segunda-feira',
#         1: 'Terça-feira',
#         2: 'Quarta-feira',
#         3: 'Quinta-feira',
#         4: 'Sexta-feira',
#         5: 'Sábado',
#         6: 'Domingo'
#     }
    
#     def __init__(self, parent=None):
#         super().__init__(parent)
#         self.init_ui()
    
#     def init_ui(self):
#         """Inicializa a interface"""
#         self.setWindowTitle('Configuração Oracle')
#         self.setMinimumWidth(500)
        
#         layout = QVBoxLayout()
#         layout.setSpacing(15)
        
#         # GroupBox principal
#         group = QGroupBox('Dados de Conexão Oracle')
#         form = QFormLayout()
#         form.setSpacing(10)
        
#         # Nome da Conexão
#         self.nome_input = QLineEdit()
#         self.nome_input.setPlaceholderText('Ex: Producao, Homologacao')
#         form.addRow('Nome da Conexão:', self.nome_input)
        
#         # Host
#         self.host_input = QLineEdit()
#         self.host_input.setPlaceholderText('192.168.1.100 ou oracle.empresa.com')
#         form.addRow('Host:', self.host_input)
        
#         # Port
#         self.port_input = QSpinBox()
#         self.port_input.setRange(1, 65535)
#         self.port_input.setValue(1521)
#         form.addRow('Porta:', self.port_input)
        
#         # Service Name
#         self.service_input = QLineEdit()
#         self.service_input.setPlaceholderText('ORCL, XE, etc')
#         form.addRow('Service Name:', self.service_input)
        
#         # Username
#         self.username_input = QLineEdit()
#         self.username_input.setPlaceholderText('usuario_oracle')
#         form.addRow('Usuário:', self.username_input)
        
#         # Password
#         self.password_input = QLineEdit()
#         self.password_input.setEchoMode(QLineEdit.Password)
#         self.password_input.setPlaceholderText('••••••••')
#         form.addRow('Senha:', self.password_input)
        
#         # ✅ NOVO: Instant Client Path (Opcional)
#         instant_client_layout = QVBoxLayout()
        
#         self.instant_client_input = QLineEdit()
#         self.instant_client_input.setPlaceholderText('/path/to/instantclient_19_20')
#         instant_client_layout.addWidget(self.instant_client_input)
        
#         instant_client_info = QLabel('Deixe em branco para usar modo thin (Oracle 12.1+)')
#         instant_client_info.setStyleSheet('color: #7f8c8d; font-size: 11px;')
#         instant_client_layout.addWidget(instant_client_info)
        
#         # Botão para selecionar diretório
#         browse_layout = QHBoxLayout()
#         browse_button = QPushButton('📁 Procurar...')
#         browse_button.clicked.connect(self.browse_instant_client)
#         browse_layout.addWidget(browse_button)
#         browse_layout.addStretch()
#         instant_client_layout.addLayout(browse_layout)
        
#         form.addRow('Instant Client (Opcional):', instant_client_layout)
        
#         group.setLayout(form)
#         layout.addWidget(group)
        
#         # Botões
#         buttons_layout = QHBoxLayout()
#         buttons_layout.addStretch()
        
#         test_button = QPushButton('Testar Conexão')
#         test_button.clicked.connect(self.test_connection)
#         buttons_layout.addWidget(test_button)
        
#         save_button = QPushButton('Salvar')
#         save_button.clicked.connect(self.save_config)
#         save_button.setDefault(True)
#         buttons_layout.addWidget(save_button)
        
#         cancel_button = QPushButton('Cancelar')
#         cancel_button.clicked.connect(self.reject)
#         buttons_layout.addWidget(cancel_button)
        
#         layout.addLayout(buttons_layout)
#         self.setLayout(layout)
        
#         self.apply_styles()
    
#     def browse_instant_client(self):
#         """Abre diálogo para selecionar diretório do Instant Client"""
#         from PyQt5.QtWidgets import QFileDialog
        
#         directory = QFileDialog.getExistingDirectory(
#             self,
#             'Selecionar Diretório do Oracle Instant Client',
#             os.path.expanduser('~')
#         )
        
#         if directory:
#             self.instant_client_input.setText(directory)
    
#     def load_config(self):
#         """Carrega configuração existente"""
#         config = db_manager.get_oracle_config()
#         if config:
#             self.nome_input.setText(config.get('nome_conexao', ''))
#             self.host_input.setText(config.get('host', ''))
#             self.port_input.setValue(config.get('port', 1521))
#             self.service_input.setText(config.get('service_name', ''))
#             self.username_input.setText(config.get('username', ''))
#             self.instant_client_input.setText(config.get('instant_client_path', ''))
#             # Senha não é carregada por segurança
    
#     def test_connection(self):
#         """Testa conexão Oracle"""
#         if not self.validate_fields():
#             return
        
#         try:
#             import oracledb
#             from core.oracle_client import OracleClient
            
#             # Preparar config temporária
#             temp_config = {
#                 'host': self.host_input.text(),
#                 'port': self.port_input.value(),
#                 'service_name': self.service_input.text(),
#                 'username': self.username_input.text(),
#                 'password': self.password_input.text(),
#                 'instant_client_path': self.instant_client_input.text().strip() or None
#             }
            
#             oracle_client = OracleClient(temp_config)
#             success, message = oracle_client.test_connection()
            
#             if success:
#                 QMessageBox.information(
#                     self,
#                     'Sucesso',
#                     f'✓ {message}'
#                 )
#             else:
#                 QMessageBox.critical(
#                     self,
#                     'Erro de Conexão',
#                     f'Não foi possível conectar ao Oracle:\n\n{message}'
#                 )
#         except Exception as e:
#             QMessageBox.critical(
#                 self,
#                 'Erro de Conexão',
#                 f'Não foi possível conectar ao Oracle:\n\n{str(e)}'
#             )
    
#     def save_config(self):
#         """Salva configuração"""
#         if not self.validate_fields():
#             return
        
#         instant_client_path = self.instant_client_input.text().strip() or None
        
#         success = db_manager.save_oracle_config(
#             nome_conexao=self.nome_input.text().strip(),
#             host=self.host_input.text().strip(),
#             port=self.port_input.value(),
#             service_name=self.service_input.text().strip(),
#             username=self.username_input.text().strip(),
#             password=self.password_input.text(),
#             instant_client_path=instant_client_path
#         )
        
#         if success:
#             QMessageBox.information(
#                 self,
#                 'Sucesso',
#                 'Configuração salva com sucesso!'
#             )
#             self.accept()
#         else:
#             QMessageBox.critical(
#                 self,
#                 'Erro',
#                 'Erro ao salvar configuração.'
#             )
    
#     def apply_styles(self):
#         """Aplica estilos"""
#         self.setStyleSheet("""
#             QGroupBox {
#                 font-weight: bold;
#                 border: 2px solid #bdc3c7;
#                 border-radius: 5px;
#                 margin-top: 10px;
#                 padding-top: 10px;
#             }
#             QComboBox, QTimeEdit {
#                 padding: 8px;
#                 border: 1px solid #bdc3c7;
#                 border-radius: 3px;
#             }
#             QPushButton {
#                 padding: 8px 20px;
#                 background-color: #9b59b6;
#                 color: white;
#                 border: none;
#                 border-radius: 3px;
#                 min-width: 100px;
#             }
#             QPushButton:hover {
#                 background-color: #8e44ad;
#             }
#         """)
    
#     def on_frequency_changed(self, freq: str):
#         """Atualiza interface conforme frequência"""
#         if freq == 'Semanal':
#             self.dias_list.setEnabled(True)
#         else:
#             self.dias_list.setEnabled(False)
#             self.dias_list.clearSelection()
    
#     def save_schedule(self):
#         """Salva agendamento"""
#         tipo = 'ENVIAR' if self.tipo_combo.currentIndex() == 0 else 'BUSCAR'
#         freq = self.freq_combo.currentText().upper()
#         hora = self.time_edit.time().toString('HH:mm')
        
#         # Pegar dias selecionados
#         dias_semana = []
#         if freq == 'SEMANAL':
#             for i in range(self.dias_list.count()):
#                 if self.dias_list.item(i).isSelected():
#                     dias_semana.append(i)
            
#             if not dias_semana:
#                 QMessageBox.warning(
#                     self,
#                     'Atenção',
#                     'Selecione pelo menos um dia da semana.'
#                 )
#                 return
        
#         success = db_manager.save_agendamento(tipo, freq, dias_semana, hora)
        
#         if success:
#             QMessageBox.information(
#                 self,
#                 'Sucesso',
#                 'Agendamento salvo com sucesso!'
#             )
#             self.accept()
#         else:
#             QMessageBox.critical(
#                 self,
#                 'Erro',
#                 'Erro ao salvar agendamento.'
#             )
# class ScheduleDialog(QDialog):
#     """Diálogo de Agendamento"""
    
#     DIAS_SEMANA = {
#         0: 'Segunda-feira',
#         1: 'Terça-feira',
#         2: 'Quarta-feira',
#         3: 'Quinta-feira',
#         4: 'Sexta-feira',
#         5: 'Sábado',
#         6: 'Domingo'
#     }
    
#     def __init__(self, parent=None):
#         super().__init__(parent)
#         self.init_ui()
    
#     def init_ui(self):
#         """Inicializa a interface"""
#         self.setWindowTitle('Configurar Agendamento')
#         self.setMinimumWidth(450)
        
#         layout = QVBoxLayout()
#         layout.setSpacing(15)
        
#         # Tipo de Operação
#         op_group = QGroupBox('Tipo de Operação')
#         op_layout = QVBoxLayout()
        
#         self.tipo_combo = QComboBox()
#         self.tipo_combo.addItems(['Enviar dados para OrionTax', 'Buscar dados da OrionTax'])
#         op_layout.addWidget(self.tipo_combo)
        
#         op_group.setLayout(op_layout)
#         layout.addWidget(op_group)
        
#         # Frequência
#         freq_group = QGroupBox('Frequência')
#         freq_layout = QVBoxLayout()
        
#         self.freq_combo = QComboBox()
#         self.freq_combo.addItems(['Diária', 'Semanal', 'Mensal'])
#         self.freq_combo.currentTextChanged.connect(self.on_frequency_changed)
#         freq_layout.addWidget(self.freq_combo)
        
#         # Lista de dias da semana
#         self.dias_list = QListWidget()
#         self.dias_list.setSelectionMode(QListWidget.MultiSelection)
#         for dia_num, dia_nome in self.DIAS_SEMANA.items():
#             self.dias_list.addItem(dia_nome)
#         self.dias_list.setMaximumHeight(150)
#         freq_layout.addWidget(self.dias_list)
        
#         freq_group.setLayout(freq_layout)
#         layout.addWidget(freq_group)
        
#         # Horário
#         hora_group = QGroupBox('Horário de Execução')
#         hora_layout = QHBoxLayout()
        
#         self.time_edit = QTimeEdit()
#         self.time_edit.setDisplayFormat('HH:mm')
#         self.time_edit.setTime(QTime(8, 0))
#         hora_layout.addWidget(QLabel('Hora:'))
#         hora_layout.addWidget(self.time_edit)
#         hora_layout.addStretch()
        
#         hora_group.setLayout(hora_layout)
#         layout.addWidget(hora_group)
        
#         # Botões
#         buttons_layout = QHBoxLayout()
#         buttons_layout.addStretch()
        
#         save_button = QPushButton('Salvar')
#         save_button.clicked.connect(self.save_schedule)
#         save_button.setDefault(True)
#         buttons_layout.addWidget(save_button)
        
#         cancel_button = QPushButton('Cancelar')
#         cancel_button.clicked.connect(self.reject)
#         buttons_layout.addWidget(cancel_button)
        
#         layout.addLayout(buttons_layout)
#         self.setLayout(layout)
        
#         self.apply_styles()
#         self.on_frequency_changed('Diária')
    
#     def apply_styles(self):
#         """Aplica estilos"""
#         self.setStyleSheet("""
#             QGroupBox {
#                 font-weight: bold;
#                 border: 2px solid #bdc3c7;
#                 border-radius: 5px;
#                 margin-top: 10px;
#                 padding-top: 10px;
#             }
#             QComboBox, QTimeEdit {
#                 padding: 8px;
#                 border: 1px solid #bdc3c7;
#                 border-radius: 3px;
#             }
#             QPushButton {
#                 padding: 8px 20px;
#                 background-color: #9b59b6;
#                 color: white;
#                 border: none;
#                 border-radius: 3px;
#                 min-width: 100px;
#             }
#             QPushButton:hover {
#                 background-color: #8e44ad;
#             }
#         """)
    
#     def on_frequency_changed(self, freq: str):
#         """Atualiza interface conforme frequência"""
#         if freq == 'Semanal':
#             self.dias_list.setEnabled(True)
#         else:
#             self.dias_list.setEnabled(False)
#             self.dias_list.clearSelection()
    
#     def save_schedule(self):
#         """Salva agendamento"""
#         tipo = 'ENVIAR' if self.tipo_combo.currentIndex() == 0 else 'BUSCAR'
#         freq = self.freq_combo.currentText().upper()
#         hora = self.time_edit.time().toString('HH:mm')
        
#         # Pegar dias selecionados
#         dias_semana = []
#         if freq == 'SEMANAL':
#             for i in range(self.dias_list.count()):
#                 if self.dias_list.item(i).isSelected():
#                     dias_semana.append(i)
            
#             if not dias_semana:
#                 QMessageBox.warning(
#                     self,
#                     'Atenção',
#                     'Selecione pelo menos um dia da semana.'
#                 )
#                 return
        
#         success = db_manager.save_agendamento(tipo, freq, dias_semana, hora)
        
#         if success:
#             QMessageBox.information(
#                 self,
#                 'Sucesso',
#                 'Agendamento salvo com sucesso!'
#             )
#             self.accept()
#         else:
#             QMessageBox.critical(
#                 self,
#                 'Erro',
#                 'Erro ao salvar agendamento.'
#             )
