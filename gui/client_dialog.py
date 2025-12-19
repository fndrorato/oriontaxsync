"""
Diálogo de Gerenciamento de Clientes
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QMessageBox, QGroupBox,
                             QFormLayout)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from config.database import db_manager


class ClientDialog(QDialog):
    """Diálogo para Adicionar/Editar Cliente"""
    
    def __init__(self, cliente_id: int = None, parent=None):
        super().__init__(parent)
        self.cliente_id = cliente_id
        self.init_ui()
        
        if cliente_id:
            self.load_cliente()
    
    def init_ui(self):
        """Inicializa a interface"""
        title = 'Editar Cliente' if self.cliente_id else 'Novo Cliente'
        self.setWindowTitle(title)
        self.setMinimumWidth(450)
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        
        # GroupBox principal
        group = QGroupBox('Dados do Cliente')
        form = QFormLayout()
        form.setSpacing(10)
        
        # Nome
        self.nome_input = QLineEdit()
        self.nome_input.setPlaceholderText('Ex: Empresa ABC Ltda')
        form.addRow('Nome:', self.nome_input)
        
        # CNPJ
        cnpj_layout = QVBoxLayout()
        
        self.cnpj_input = QLineEdit()
        self.cnpj_input.setPlaceholderText('12345678000190 ou 12.345.678/0001-90')
        self.cnpj_input.setMaxLength(18)  # Com formatação
        cnpj_layout.addWidget(self.cnpj_input)
        
        cnpj_info = QLabel('Digite apenas os números (14 dígitos)')
        cnpj_info.setStyleSheet('color: #7f8c8d; font-size: 11px;')
        cnpj_layout.addWidget(cnpj_info)
        
        form.addRow('CNPJ:', cnpj_layout)
        
        group.setLayout(form)
        layout.addWidget(group)
        
        # Botões
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        save_button = QPushButton('Salvar')
        save_button.clicked.connect(self.save_cliente)
        save_button.setDefault(True)
        buttons_layout.addWidget(save_button)
        
        cancel_button = QPushButton('Cancelar')
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)
        
        layout.addLayout(buttons_layout)
        self.setLayout(layout)
        
        self.apply_styles()
        
        # Focar no campo nome
        self.nome_input.setFocus()
    
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
            QLineEdit {
                padding: 8px;
                border: 1px solid #bdc3c7;
                border-radius: 3px;
            }
            QLineEdit:focus {
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
    
    def load_cliente(self):
        """Carrega dados do cliente para edição"""
        cliente = db_manager.get_cliente(self.cliente_id)
        if cliente:
            self.nome_input.setText(cliente['nome'])
            # Formatar CNPJ para exibição
            cnpj_formatado = db_manager.format_cnpj(cliente['cnpj'])
            self.cnpj_input.setText(cnpj_formatado)
    
    def validate_cnpj(self, cnpj: str) -> bool:
        """
        Valida CNPJ
        
        Args:
            cnpj: CNPJ (pode estar formatado ou não)
        
        Returns:
            True se válido
        """
        # Limpar CNPJ
        cnpj_limpo = ''.join(filter(str.isdigit, cnpj))
        
        if len(cnpj_limpo) != 14:
            return False
        
        # Validação básica: não pode ter todos os dígitos iguais
        if cnpj_limpo == cnpj_limpo[0] * 14:
            return False
        
        return True
    
    def save_cliente(self):
        """Salva cliente"""
        nome = self.nome_input.text().strip()
        cnpj = self.cnpj_input.text().strip()
        
        # Validações
        if not nome:
            QMessageBox.warning(self, 'Atenção', 'Informe o nome do cliente.')
            self.nome_input.setFocus()
            return
        
        if not cnpj:
            QMessageBox.warning(self, 'Atenção', 'Informe o CNPJ do cliente.')
            self.cnpj_input.setFocus()
            return
        
        if not self.validate_cnpj(cnpj):
            QMessageBox.warning(
                self, 
                'CNPJ Inválido', 
                'O CNPJ deve conter exatamente 14 dígitos.'
            )
            self.cnpj_input.setFocus()
            return
        
        # Salvar
        if self.cliente_id:
            # Atualizar
            success = db_manager.update_cliente(self.cliente_id, nome, cnpj)
            message = 'Cliente atualizado com sucesso!' if success else 'Erro ao atualizar cliente.'
        else:
            # Criar novo
            success = db_manager.create_cliente(nome, cnpj)
            if not success:
                QMessageBox.critical(
                    self,
                    'Erro',
                    'Erro ao criar cliente. Verifique se o CNPJ já está cadastrado.'
                )
                return
            message = 'Cliente criado com sucesso!'
        
        if success:
            QMessageBox.information(self, 'Sucesso', message)
            self.accept()
        else:
            QMessageBox.critical(self, 'Erro', 'Erro ao salvar cliente.')