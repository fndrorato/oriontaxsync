"""
Scheduler - Gerencia agendamentos de sincronização
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import logging
import threading


class Scheduler:
    """Gerenciador de agendamentos"""
    
    def __init__(self, db_manager):
        """
        Inicializa o scheduler
        
        Args:
            db_manager: Instância do DatabaseManager
        """
        self.db_manager = db_manager
        self.scheduler = BackgroundScheduler()
        self.logger = logging.getLogger(__name__)
        self.jobs = {}  # Dicionário para rastrear jobs: {id: job}
    
    def start(self):
        """Inicia o scheduler"""
        try:
            self.scheduler.start()
            self.logger.info("Scheduler iniciado")
            
            # Carregar agendamentos do banco
            self.load_schedules()
            
        except Exception as e:
            self.logger.error(f"Erro ao iniciar scheduler: {e}")
    
    def stop(self):
        """Para o scheduler"""
        try:
            self.scheduler.shutdown(wait=False)
            self.logger.info("Scheduler parado")
        except Exception as e:
            self.logger.error(f"Erro ao parar scheduler: {e}")
    
    def load_schedules(self):
        """Carrega todos os agendamentos do banco de dados"""
        try:
            schedules = self.db_manager.get_all_schedules()
            
            for schedule in schedules:
                self.add_job(schedule)
            
            self.logger.info(f"{len(schedules)} agendamentos carregados")
            
        except Exception as e:
            self.logger.error(f"Erro ao carregar agendamentos: {e}")
    
    def add_job(self, schedule: dict):
        """
        Adiciona um job ao scheduler
        
        Args:
            schedule: Dict com dados do agendamento
                - id: int
                - operation_type: str ('ENVIAR' ou 'BUSCAR')
                - schedule_type: str ('daily', 'weekly', 'monthly')
                - schedule_time: str (HH:MM)
                - schedule_day: int (dia do mês para 'monthly', dia da semana para 'weekly')
                - is_active: bool
        """
        try:
            if not schedule['is_active']:
                self.logger.info(f"Agendamento {schedule['id']} está inativo")
                return
            
            # Remover job existente se houver
            if schedule['id'] in self.jobs:
                self.remove_job(schedule['id'])
            
            # Criar trigger baseado no tipo de agendamento
            trigger = self._create_trigger(schedule)
            
            if trigger is None:
                self.logger.error(f"Não foi possível criar trigger para agendamento {schedule['id']}")
                return
            
            # Adicionar job ao scheduler
            job = self.scheduler.add_job(
                func=self._execute_sync,
                trigger=trigger,
                args=[schedule['operation_type']],
                id=f"schedule_{schedule['id']}",
                name=f"{schedule['operation_type']}",
                replace_existing=True
            )
            
            # Armazenar referência do job
            self.jobs[schedule['id']] = job
            
            self.logger.info(f"Job adicionado: {schedule['id']} - {schedule['operation_type']}")
            
        except Exception as e:
            self.logger.error(f"Erro ao adicionar job: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
    
    def remove_job(self, schedule_id: int):
        """
        Remove um job do scheduler
        
        Args:
            schedule_id: ID do agendamento
        """
        try:
            job_id = f"schedule_{schedule_id}"
            
            if job_id in [job.id for job in self.scheduler.get_jobs()]:
                self.scheduler.remove_job(job_id)
                self.logger.info(f"Job removido: {schedule_id}")
            
            # Remover do dicionário de jobs
            if schedule_id in self.jobs:
                del self.jobs[schedule_id]
                
        except Exception as e:
            self.logger.error(f"Erro ao remover job: {e}")
    
    def update_job(self, schedule: dict):
        """
        Atualiza um job existente
        
        Args:
            schedule: Dict com dados atualizados do agendamento
        """
        try:
            # Remover job antigo
            self.remove_job(schedule['id'])
            
            # Adicionar job atualizado
            self.add_job(schedule)
            
            self.logger.info(f"Job atualizado: {schedule['id']}")
            
        except Exception as e:
            self.logger.error(f"Erro ao atualizar job: {e}")
    
    def _create_trigger(self, schedule: dict):
        """
        Cria um CronTrigger baseado no tipo de agendamento
        
        Args:
            schedule: Dict com dados do agendamento
            
        Returns:
            CronTrigger ou None
        """
        try:
            schedule_time = schedule['schedule_time']  # "HH:MM"
            hour, minute = schedule_time.split(':')
            hour = int(hour)
            minute = int(minute)
            
            schedule_type = schedule['schedule_type']
            
            if schedule_type == 'daily':
                # Executa todos os dias no horário especificado
                trigger = CronTrigger(
                    hour=hour,
                    minute=minute
                )
                
            elif schedule_type == 'weekly':
                # Executa uma vez por semana no dia especificado
                # 0 = Segunda, 1 = Terça, ..., 6 = Domingo
                day_of_week = schedule['schedule_day']
                trigger = CronTrigger(
                    day_of_week=day_of_week,
                    hour=hour,
                    minute=minute
                )
                
            elif schedule_type == 'monthly':
                # Executa uma vez por mês no dia especificado
                day = schedule['schedule_day']
                trigger = CronTrigger(
                    day=day,
                    hour=hour,
                    minute=minute
                )
                
            else:
                self.logger.error(f"Tipo de agendamento inválido: {schedule_type}")
                return None
            
            return trigger
            
        except Exception as e:
            self.logger.error(f"Erro ao criar trigger: {e}")
            return None
    
    def _execute_sync(self, operation_type: str):
        """
        Executa a sincronização agendada
        ✅ EXECUTA A MESMA LÓGICA DOS BOTÕES DA INTERFACE
        
        Args:
            operation_type: 'ENVIAR' ou 'BUSCAR'
        """
        try:
            self.logger.info(f"========================================")
            self.logger.info(f"Executando sincronização agendada: {operation_type}")
            self.logger.info(f"========================================")
            
            # ✅ Buscar configurações (THREAD-SAFE)
            oracle_config = self.db_manager.get_oracle_config_threadsafe()
            oriontax_config = self.db_manager.get_oriontax_config_threadsafe()
            
            if not oracle_config:
                self.logger.error("Configuração Oracle não encontrada")
                return
            
            if not oriontax_config:
                self.logger.error("Configuração OrionTax não encontrada")
                return
            
            # ✅ Buscar todos os clientes ativos (THREAD-SAFE)
            clientes = self.db_manager.get_all_clientes_threadsafe()
            
            if not clientes:
                self.logger.warning("Nenhum cliente cadastrado")
                return
            
            # ✅ Executar para CADA cliente
            for cliente in clientes:
                cnpj = cliente['cnpj']
                nome = cliente['nome']
                
                self.logger.info(f"Processando cliente: {nome} (CNPJ: {cnpj})")
                
                # Executar em thread separada para não bloquear
                thread = threading.Thread(
                    target=self._execute_sync_for_client,
                    args=(operation_type, oracle_config, oriontax_config, cnpj, nome)
                )
                thread.daemon = True
                thread.start()
            
            # Registrar última execução (THREAD-SAFE)
            self.db_manager.update_schedule_last_run(operation_type)
            
            self.logger.info(f"Sincronização agendada iniciada para {len(clientes)} cliente(s)")
            
        except Exception as e:
            self.logger.error(f"Erro ao executar sincronização: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
    
    def _execute_sync_for_client(self, operation_type: str, oracle_config: dict, 
                                 oriontax_config: dict, cnpj: str, nome_cliente: str):
        """
        Executa sincronização para um cliente específico
        ✅ MESMA LÓGICA DA WorkerThread
        
        Args:
            operation_type: 'ENVIAR' ou 'BUSCAR'
            oracle_config: Configuração Oracle
            oriontax_config: Configuração OrionTax
            cnpj: CNPJ do cliente
            nome_cliente: Nome do cliente
        """
        from datetime import datetime
        from core.oracle_client import OracleClient
        from core.oriontax_client import OrionTaxClient
        
        try:
            start_time = datetime.now()
            
            if operation_type == 'ENVIAR':
                # ✅ ENVIAR: Oracle → PostgreSQL (OrionTax)
                
                self.logger.info(f'[{nome_cliente}] Conectando ao Oracle...')
                oracle_client = OracleClient(oracle_config)
                oracle_client.connect()
                
                self.logger.info(f'[{nome_cliente}] Lendo VIEWs do Oracle (CNPJ: {cnpj})...')
                dataframes = oracle_client.read_views_to_dataframes()
                
                total_records = sum(len(df) for df in dataframes.values())
                self.logger.info(f'[{nome_cliente}] ✓ {total_records} registros lidos do Oracle')
                
                oracle_client.disconnect()
                
                self.logger.info(f'[{nome_cliente}] Conectando ao OrionTax...')
                oriontax_client = OrionTaxClient(oriontax_config)
                oriontax_client.connect()
                
                self.logger.info(f'[{nome_cliente}] Enviando dados para OrionTax...')
                success, message = oriontax_client.write_dataframes_to_views(cnpj, dataframes)
                
                oriontax_client.disconnect()
                
                tempo = (datetime.now() - start_time).total_seconds()
                
                if success:
                    self.logger.info(f'[{nome_cliente}] ✓ Dados enviados com sucesso! ({tempo:.2f}s)')
                    self.logger.info(f'[{nome_cliente}] {message}')
                    
                    # ✅ Registrar no log do banco (THREAD-SAFE)
                    self.db_manager.add_log_threadsafe(
                        tipo_operacao='ENVIAR',
                        status='SUCESSO',
                        mensagem=f'Cliente: {nome_cliente} - {message}',
                        registros=total_records,
                        tempo=tempo
                    )
                else:
                    self.logger.error(f'[{nome_cliente}] ✗ Erro ao enviar: {message}')
                    
                    self.db_manager.add_log_threadsafe(
                        tipo_operacao='ENVIAR',
                        status='ERRO',
                        mensagem=f'Cliente: {nome_cliente}',
                        error_details=message
                    )
                
            elif operation_type == 'BUSCAR':
                # ✅ BUSCAR: PostgreSQL (OrionTax) → Oracle
                
                self.logger.info(f'[{nome_cliente}] Conectando ao OrionTax...')
                oriontax_client = OrionTaxClient(oriontax_config)
                oriontax_client.connect()
                
                self.logger.info(f'[{nome_cliente}] Lendo tabelas TMP do OrionTax (CNPJ: {cnpj})...')
                dataframes = oriontax_client.read_tmp_tables_to_dataframes(cnpj)
                
                total_records = sum(len(df) for df in dataframes.values())
                self.logger.info(f'[{nome_cliente}] ✓ {total_records} registros lidos do OrionTax')
                
                oriontax_client.disconnect()
                
                self.logger.info(f'[{nome_cliente}] Conectando ao Oracle...')
                oracle_client = OracleClient(oracle_config)
                oracle_client.connect()
                
                self.logger.info(f'[{nome_cliente}] Gravando dados no Oracle...')
                success, message = oracle_client.write_dataframes_to_tmp_tables(dataframes)
                
                oracle_client.disconnect()
                
                tempo = (datetime.now() - start_time).total_seconds()
                
                if success:
                    self.logger.info(f'[{nome_cliente}] ✓ Dados recebidos com sucesso! ({tempo:.2f}s)')
                    self.logger.info(f'[{nome_cliente}] {message}')
                    
                    self.db_manager.add_log_threadsafe(
                        tipo_operacao='BUSCAR',
                        status='SUCESSO',
                        mensagem=f'Cliente: {nome_cliente} - {message}',
                        registros=total_records,
                        tempo=tempo
                    )
                else:
                    self.logger.error(f'[{nome_cliente}] ✗ Erro ao buscar: {message}')
                    
                    self.db_manager.add_log_threadsafe(
                        tipo_operacao='BUSCAR',
                        status='ERRO',
                        mensagem=f'Cliente: {nome_cliente}',
                        error_details=message
                    )
        
        except Exception as e:
            import traceback
            error_msg = f'Erro: {str(e)}\n\n{traceback.format_exc()}'
            self.logger.error(f'[{nome_cliente}] {error_msg}')
            
            self.db_manager.add_log_threadsafe(
                tipo_operacao=operation_type,
                status='ERRO',
                mensagem=f'Cliente: {nome_cliente}',
                error_details=error_msg
            )
    
    def get_jobs(self):
        """
        Retorna lista de jobs ativos
        
        Returns:
            Lista de dicts com informações dos jobs
        """
        jobs = []
        
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time
            
            jobs.append({
                'id': job.id,
                'name': job.name,
                'next_run': next_run.strftime('%d/%m/%Y %H:%M:%S') if next_run else 'N/A'
            })
        
        return jobs