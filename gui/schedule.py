"""
Schedule Dialog - Diálogo para gerenciar agendamentos
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QRadioButton, QTimeEdit, QSpinBox, QCheckBox,
    QGroupBox, QButtonGroup, QMessageBox, QWidget
)
from PyQt5.QtCore import QTime, Qt
import logging


class ScheduleDialog(QDialog):
    """Diálogo para criar/editar agendamentos"""
    
    def __init__(self, parent, db_manager, schedule=None):
        """
        Inicializa o diálogo
        
        Args:
            parent: Widget pai
            db_manager: Instância do DatabaseManager
            schedule: Dict com dados do agendamento (None para novo)
        """
        super().__init__(parent)
        self.db_manager = db_manager
        self.schedule = schedule  # Armazenar agendamento para edição
        self.schedule_id = None
        self.logger = logging.getLogger(__name__)
        
        self.setWindowTitle("Novo Agendamento" if not schedule else "Editar Agendamento")
        self.setModal(True)
        self.setMinimumWidth(500)
        
        self.init_ui()
        
        # Se está editando, preencher campos
        if schedule:
            self.load_schedule_data()
    
    def init_ui(self):
        """Inicializa interface"""
        layout = QVBoxLayout()
        
        # Operação
        operation_group = QGroupBox("Operação")
        operation_layout = QVBoxLayout()
        
        self.operation_combo = QComboBox()
        self.operation_combo.addItems(['ENVIAR', 'BUSCAR'])
        operation_layout.addWidget(self.operation_combo)
        
        operation_group.setLayout(operation_layout)
        layout.addWidget(operation_group)
        
        # ✅ REMOVIDO: Seção de Cliente
        
        # Tipo de Agendamento
        schedule_group = QGroupBox("Tipo de Agendamento")
        schedule_layout = QVBoxLayout()
        
        self.schedule_button_group = QButtonGroup()
        
        self.daily_radio = QRadioButton("Diário")
        self.weekly_radio = QRadioButton("Semanal")
        self.monthly_radio = QRadioButton("Mensal")
        
        self.schedule_button_group.addButton(self.daily_radio)
        self.schedule_button_group.addButton(self.weekly_radio)
        self.schedule_button_group.addButton(self.monthly_radio)
        
        self.daily_radio.setChecked(True)
        
        schedule_layout.addWidget(self.daily_radio)
        schedule_layout.addWidget(self.weekly_radio)
        schedule_layout.addWidget(self.monthly_radio)
        
        # Conectar sinais para mostrar/ocultar campo de dia
        self.daily_radio.toggled.connect(self.update_day_visibility)
        self.weekly_radio.toggled.connect(self.update_day_visibility)
        self.monthly_radio.toggled.connect(self.update_day_visibility)
        
        schedule_group.setLayout(schedule_layout)
        layout.addWidget(schedule_group)
        
        # Dia (para semanal/mensal)
        day_group = QGroupBox("Dia")
        day_layout = QHBoxLayout()
        
        self.day_label = QLabel("Dia:")
        self.day_spin = QSpinBox()
        self.day_spin.setMinimum(0)
        self.day_spin.setMaximum(31)
        self.day_spin.setValue(1)
        
        day_layout.addWidget(self.day_label)
        day_layout.addWidget(self.day_spin)
        day_layout.addStretch()
        
        day_group.setLayout(day_layout)
        self.day_group = day_group
        layout.addWidget(day_group)
        
        # Horário
        time_group = QGroupBox("Horário")
        time_layout = QHBoxLayout()
        
        time_layout.addWidget(QLabel("Horário:"))
        self.time_edit = QTimeEdit()
        self.time_edit.setTime(QTime(8, 0))
        self.time_edit.setDisplayFormat("HH:mm")
        time_layout.addWidget(self.time_edit)
        time_layout.addStretch()
        
        time_group.setLayout(time_layout)
        layout.addWidget(time_group)
        
        # Ativo
        self.active_check = QCheckBox("Agendamento Ativo")
        self.active_check.setChecked(True)
        layout.addWidget(self.active_check)
        
        # Botões
        button_layout = QHBoxLayout()
        
        save_btn = QPushButton("Salvar")
        save_btn.clicked.connect(self.save_schedule)
        
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        # Atualizar visibilidade inicial
        self.update_day_visibility()
    
    # ✅ REMOVIDO: método load_clients()
    
    def update_day_visibility(self):
        """Atualiza visibilidade do campo de dia"""
        if self.daily_radio.isChecked():
            self.day_group.setVisible(False)
        elif self.weekly_radio.isChecked():
            self.day_group.setVisible(True)
            self.day_label.setText("Dia da Semana (0=Segunda, 6=Domingo):")
            self.day_spin.setMaximum(6)
            self.day_spin.setValue(0)
        else:  # monthly
            self.day_group.setVisible(True)
            self.day_label.setText("Dia do Mês:")
            self.day_spin.setMaximum(31)
            self.day_spin.setValue(1)
    
    def load_schedule_data(self):
        """Preenche campos com dados do agendamento"""
        if not self.schedule:
            return
        
        # Selecionar operação
        operation = self.schedule['operation_type']
        index = self.operation_combo.findText(operation)
        if index >= 0:
            self.operation_combo.setCurrentIndex(index)
        
        # ✅ REMOVIDO: Selecionar cliente
        
        # Tipo de agendamento
        schedule_type = self.schedule['schedule_type']
        if schedule_type == 'daily':
            self.daily_radio.setChecked(True)
        elif schedule_type == 'weekly':
            self.weekly_radio.setChecked(True)
        elif schedule_type == 'monthly':
            self.monthly_radio.setChecked(True)
        
        # Horário
        hour, minute = self.schedule['schedule_time'].split(':')
        time = QTime(int(hour), int(minute))
        self.time_edit.setTime(time)
        
        # Dia (se aplicável)
        if schedule_type == 'weekly' and self.schedule.get('schedule_day') is not None:
            self.day_spin.setValue(self.schedule['schedule_day'])
        elif schedule_type == 'monthly' and self.schedule.get('schedule_day') is not None:
            self.day_spin.setValue(self.schedule['schedule_day'])
        
        # Ativo
        self.active_check.setChecked(self.schedule['is_active'])
    
    def save_schedule(self):
        """Salva agendamento"""
        operation = self.operation_combo.currentText()
        
        # ✅ REMOVIDO: Validação de cliente
        
        # Tipo de agendamento
        if self.daily_radio.isChecked():
            schedule_type = 'daily'
            schedule_day = None
        elif self.weekly_radio.isChecked():
            schedule_type = 'weekly'
            schedule_day = self.day_spin.value()
        else:
            schedule_type = 'monthly'
            schedule_day = self.day_spin.value()
        
        # Horário
        time = self.time_edit.time()
        schedule_time = time.toString('HH:mm')
        
        # Ativo
        is_active = self.active_check.isChecked()
        
        try:
            # ✅ Se está editando, fazer UPDATE (SEM client_id)
            if self.schedule:
                self.db_manager.update_schedule(
                    schedule_id=self.schedule['id'],
                    operation_type=operation,
                    schedule_type=schedule_type,
                    schedule_time=schedule_time,
                    schedule_day=schedule_day,
                    is_active=is_active
                )
                self.schedule_id = self.schedule['id']
            else:
                # ✅ Criar novo (SEM client_id)
                self.schedule_id = self.db_manager.create_schedule(
                    operation_type=operation,
                    schedule_type=schedule_type,
                    schedule_time=schedule_time,
                    schedule_day=schedule_day,
                    is_active=is_active
                )
            
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao salvar agendamento: {e}")