"""
Cliente OrionTax - Gerencia conexão e operações com PostgreSQL
"""
import psycopg2
import pandas as pd
import logging
from typing import Dict, Tuple
from psycopg2.extras import execute_values
import numpy as np


class OrionTaxClient:
    """Cliente para conexão e operações com OrionTax (PostgreSQL)"""
    
    def __init__(self, config: Dict):
        """
        Inicializa o cliente OrionTax
        
        Args:
            config: Dicionário com configuração de conexão
                - host: str
                - port: int
                - database_name: str
                - username: str
                - password: str
                - use_ssl: bool
        """
        self.config = config
        self.connection = None
        self.logger = logging.getLogger(__name__)
    
    def connect(self) -> bool:
        """
        Conecta ao PostgreSQL
        
        Returns:
            True se conectou com sucesso
        """
        try:
            sslmode = 'require' if self.config.get('use_ssl', True) else 'disable'
            
            self.connection = psycopg2.connect(
                host=self.config['host'],
                port=self.config['port'],
                database=self.config['database_name'],
                user=self.config['username'],
                password=self.config['password'],
                sslmode=sslmode,
                connect_timeout=10
            )
            
            # Importante: desabilitar autocommit para ter controle das transações
            self.connection.autocommit = False
            
            self.logger.info(f"✓ Conectado ao OrionTax: {self.config['host']}")
            return True
            
        except Exception as e:
            self.logger.error(f"Erro ao conectar ao OrionTax: {e}")
            raise
    
    def disconnect(self):
        """Desconecta do PostgreSQL"""
        if self.connection:
            try:
                self.connection.close()
                self.logger.info("Desconectado do OrionTax")
            except Exception as e:
                self.logger.error(f"Erro ao desconectar: {e}")
            finally:
                self.connection = None
    
    def test_connection(self) -> Tuple[bool, str]:
        """
        Testa a conexão
        
        Returns:
            Tuple (sucesso, mensagem)
        """
        try:
            self.connect()
            
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            cursor.close()
            
            self.disconnect()
            
            return True, "Conexão bem-sucedida"
            
        except Exception as e:
            return False, f"Erro: {str(e)}"
    
    def _clean_dataframe_for_insert(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Limpa DataFrame para inserção no PostgreSQL
        - Substitui NaN, None, pd.NA por None do Python
        - Converte tipos problemáticos
        """
        df_clean = df.copy()
        
        # Substituir NaN, pd.NA, np.nan por None
        df_clean = df_clean.replace({pd.NA: None, np.nan: None, float('nan'): None})
        
        # Converter colunas object que podem ter NaN
        for col in df_clean.columns:
            if df_clean[col].dtype == 'object':
                df_clean[col] = df_clean[col].where(pd.notna(df_clean[col]), None)
        
        return df_clean
    
    def _ensure_constraint_exists(self, table_name: str, conflict_cols: list):
        """
        Verifica se a constraint existe, senão cria
        """
        try:
            constraint_name = f"{table_name}_unique_constraint"
            
            cursor = self.connection.cursor()
            
            # Verificar se constraint existe
            cursor.execute("""
                SELECT COUNT(*)
                FROM information_schema.table_constraints
                WHERE table_name = %s
                AND constraint_name = %s
                AND constraint_type = 'UNIQUE'
            """, (table_name, constraint_name))
            
            exists = cursor.fetchone()[0] > 0
            
            if not exists:
                self.logger.info(f"Criando constraint única em {table_name} para {conflict_cols}")
                
                # Criar constraint
                cols_sql = ', '.join(conflict_cols)
                cursor.execute(f"""
                    ALTER TABLE {table_name}
                    ADD CONSTRAINT {constraint_name}
                    UNIQUE ({cols_sql})
                """)
                
                self.connection.commit()
                self.logger.info(f"✓ Constraint criada: {constraint_name}")
            
            cursor.close()
            
        except Exception as e:
            self.logger.warning(f"Erro ao criar constraint: {e}")
            self.connection.rollback()
            # Não falhar se a constraint já existe
            
    def _get_table_columns(self, table_name: str) -> list:
        """
        Obtém lista de colunas que existem na tabela PostgreSQL
        
        Returns:
            Lista de nomes de colunas (lowercase)
        """
        try:
            cursor = self.connection.cursor()
            
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = %s
                ORDER BY ordinal_position
            """, (table_name,))
            
            columns = [row[0] for row in cursor.fetchall()]
            cursor.close()
            
            return columns
            
        except Exception as e:
            self.logger.error(f"Erro ao obter colunas da tabela {table_name}: {e}")
            return []
    
    def _filter_dataframe_columns(self, df: pd.DataFrame, table_name: str) -> pd.DataFrame:
        """
        Filtra DataFrame para incluir apenas colunas que existem na tabela destino
        
        Args:
            df: DataFrame original
            table_name: Nome da tabela PostgreSQL
            
        Returns:
            DataFrame com apenas colunas válidas
        """
        # Obter colunas da tabela
        valid_columns = self._get_table_columns(table_name)
        
        if not valid_columns:
            self.logger.warning(f"Não foi possível obter colunas de {table_name}, usando todas")
            return df
        
        # Colunas do DataFrame (lowercase)
        df_columns = [c.lower() for c in df.columns]
        
        # Colunas que existem em ambos
        common_columns = [c for c in df_columns if c in valid_columns]
        
        # Colunas que estão no DataFrame mas não na tabela
        extra_columns = [c for c in df_columns if c not in valid_columns]
        
        if extra_columns:
            self.logger.warning(f"Removendo {len(extra_columns)} colunas não existentes na tabela:")
            for col in extra_columns:
                self.logger.warning(f"  - {col}")
        
        # Colunas que estão na tabela mas não no DataFrame
        missing_columns = [c for c in valid_columns if c not in df_columns]
        
        if missing_columns:
            self.logger.info(f"Colunas da tabela ausentes no DataFrame ({len(missing_columns)}): {missing_columns[:5]}...")
        
        # Filtrar DataFrame
        df_filtered = df[[c for c in df.columns if c.lower() in common_columns]].copy()
        
        self.logger.info(f"DataFrame filtrado: {len(df.columns)} → {len(df_filtered.columns)} colunas")
        
        return df_filtered            
    
    def upsert_dataframe_psycopg2(
        self,
        table_name: str,
        df: pd.DataFrame,
        conflict_cols: list,
        update_cols: list
    ) -> int:
        """
        Faz UPSERT (INSERT ... ON CONFLICT DO UPDATE) no PostgreSQL
        
        Args:
            table_name: Nome da tabela
            df: DataFrame com dados
            conflict_cols: Colunas da chave única (ex: ['cnpj', 'codigo_produto'])
            update_cols: Colunas a atualizar em caso de conflito
            
        Returns:
            Número de registros processados
        """
        if df.empty:
            self.logger.info(f"DataFrame vazio para {table_name}, pulando...")
            return 0
        
        try:
            # Limpar DataFrame
            df_clean = self._clean_dataframe_for_insert(df)
            
            # Garantir que constraint existe
            self._ensure_constraint_exists(table_name, conflict_cols)
            
            # Preparar colunas e valores
            cols = list(df_clean.columns)
            values = [tuple(row) for row in df_clean.to_numpy()]
            
            # Construir SQL de UPSERT
            cols_sql = ', '.join(cols)
            
            # Placeholder para VALUES: (%s, %s, %s, ...)
            placeholders = ', '.join(['%s'] * len(cols))
            
            # Cláusula UPDATE SET
            update_set = ', '.join([f"{col} = EXCLUDED.{col}" for col in update_cols])
            
            insert_sql = f"""
                INSERT INTO {table_name} ({cols_sql})
                VALUES %s
                ON CONFLICT ({', '.join(conflict_cols)})
                DO UPDATE SET {update_set}
            """
            
            self.logger.info(f"Executando UPSERT em {table_name}: {len(values)} registros")
            
            # Executar em chunks para performance
            chunk_size = 1000
            total_inserted = 0
            
            with self.connection.cursor() as cursor:
                for i in range(0, len(values), chunk_size):
                    chunk = values[i:i + chunk_size]
                    
                    execute_values(
                        cursor,
                        insert_sql,
                        chunk,
                        page_size=chunk_size
                    )
                    
                    total_inserted += len(chunk)
                    
                    if (i // chunk_size + 1) % 10 == 0:  # Log a cada 10 chunks
                        self.logger.info(f"  Processados {total_inserted}/{len(values)} registros...")
            
            self.logger.info(f"✓ {total_inserted} registros processados em {table_name}")
            
            return total_inserted
            
        except Exception as e:
            self.logger.error(f"Erro no UPSERT de {table_name}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            raise
        
    def _remove_duplicates(self, df: pd.DataFrame, key_cols: list) -> pd.DataFrame:
        """
        Remove duplicatas do DataFrame baseado nas colunas-chave
        Mantém a ÚLTIMA ocorrência
        
        Args:
            df: DataFrame
            key_cols: Colunas que formam a chave única
            
        Returns:
            DataFrame sem duplicatas
        """
        original_count = len(df)
        
        # Remover duplicatas mantendo a última ocorrência
        df_unique = df.drop_duplicates(subset=key_cols, keep='last')
        
        duplicates_count = original_count - len(df_unique)
        
        if duplicates_count > 0:
            self.logger.warning(f"⚠️  Removidas {duplicates_count} duplicatas (chave: {key_cols})")
            self.logger.warning(f"   {original_count} → {len(df_unique)} registros")
        else:
            self.logger.info(f"✓ Nenhuma duplicata encontrada")
        
        return df_unique        
    
    def _truncate_string_columns(self, df: pd.DataFrame, table_name: str) -> pd.DataFrame:
        """
        Trunca colunas de texto que excedem o tamanho máximo da tabela
        
        Args:
            df: DataFrame
            table_name: Nome da tabela PostgreSQL
            
        Returns:
            DataFrame com valores truncados
        """
        try:
            cursor = self.connection.cursor()
            
            # Buscar colunas CHAR/VARCHAR com limite de tamanho
            cursor.execute("""
                SELECT 
                    column_name,
                    character_maximum_length
                FROM information_schema.columns
                WHERE table_name = %s
                AND data_type IN ('character', 'character varying')
                AND character_maximum_length IS NOT NULL
            """, (table_name,))
            
            char_columns = {row[0]: row[1] for row in cursor.fetchall()}
            cursor.close()
            
            if not char_columns:
                return df
            
            df_truncated = df.copy()
            truncated_count = 0
            
            for col_name, max_length in char_columns.items():
                if col_name not in df_truncated.columns:
                    continue
                
                # Converter para string
                df_truncated[col_name] = df_truncated[col_name].astype(str)
                
                # Substituir 'nan' string por None
                df_truncated[col_name] = df_truncated[col_name].replace('nan', None)
                
                # Verificar se há valores que excedem
                too_long_mask = df_truncated[col_name].str.len() > max_length
                too_long_count = too_long_mask.sum()
                
                if too_long_count > 0:
                    self.logger.warning(
                        f"⚠️  Truncando {too_long_count} valores em '{col_name}' "
                        f"(max={max_length})"
                    )
                    
                    # Mostrar exemplos
                    examples = df_truncated.loc[too_long_mask, col_name].head(3)
                    for val in examples:
                        if val:
                            self.logger.warning(f"     [{len(val)} chars] {val[:50]}...")
                    
                    # Truncar valores
                    df_truncated.loc[too_long_mask, col_name] = (
                        df_truncated.loc[too_long_mask, col_name].str[:max_length]
                    )
                    
                    truncated_count += too_long_count
            
            if truncated_count > 0:
                self.logger.warning(f"✂️  Total de valores truncados: {truncated_count}")
            else:
                self.logger.info("✓ Nenhum valor precisa ser truncado")
            
            return df_truncated
            
        except Exception as e:
            self.logger.warning(f"Erro ao truncar colunas: {e}")
            return df    
    
    def write_dataframes_to_views(self, cnpj: str, dataframes: Dict[str, pd.DataFrame]) -> Tuple[bool, str]:
        """
        Grava DataFrames nas VIEWs/Tabelas do PostgreSQL (dados vindos do Oracle)
        Usa lógica de UPSERT (Update or Insert) baseado na chave: CNPJ + CODIGO_PRODUTO
        
        ENVIAR: Oracle VIEWs → PostgreSQL VIEWs
        
        Args:
            cnpj: CNPJ do cliente
            dataframes: Dict com 4 DataFrames do Oracle
                - icms_entrada
                - icms_saida (vindo de MXF_VW_ICMS)
                - pis_cofins
                - cbs_ibs
            
        Returns:
            Tuple (sucesso, mensagem)
        """
        try:
            if not self.connection:
                self.connect()
            
            total_processed = 0
            
            # Mapeamento de chaves para nomes de tabelas
            mapping = {
                'icms_entrada': 'mxf_vw_icms_entrada',
                'icms_saida': 'mxf_vw_icms',
                'pis_cofins': 'mxf_vw_pis_cofins',
                'cbs_ibs': 'mxf_vw_cbs_ibs'
            }
            
            for key, table_name in mapping.items():
                if key not in dataframes:
                    self.logger.info(f"DataFrame '{key}' não encontrado, pulando...")
                    continue
                
                df = dataframes[key]
                
                if df.empty:
                    self.logger.info(f"DataFrame '{key}' está vazio, pulando...")
                    continue
                
                # Fazer cópia para não modificar original
                df = df.copy()
                
                # Converter nomes de colunas para lowercase (padrão PostgreSQL)
                df.columns = [c.lower() for c in df.columns]
                
                # Adicionar/substituir CNPJ
                df['cnpj'] = cnpj
                
                # Garantir que codigo_produto não seja None
                if 'codigo_produto' not in df.columns:
                    raise ValueError(f"Coluna 'codigo_produto' não encontrada no DataFrame '{key}'")
                
                # Remover linhas onde codigo_produto é None
                original_count = len(df)
                df = df[df['codigo_produto'].notna()]
                removed_count = original_count - len(df)
                
                if removed_count > 0:
                    self.logger.warning(f"  Removidas {removed_count} linhas sem codigo_produto")
                
                if df.empty:
                    self.logger.warning(f"DataFrame '{key}' ficou vazio após filtrar codigo_produto nulos")
                    continue
                
                self.logger.info(f"\n{'='*60}")
                self.logger.info(f"Processando {table_name}")
                self.logger.info(f"Registros: {len(df)}")
                self.logger.info(f"Colunas originais: {len(df.columns)}")
                
                # ✅ FILTRAR COLUNAS - Manter apenas as que existem na tabela
                df = self._filter_dataframe_columns(df, table_name)
                
                if df.empty:
                    self.logger.warning(f"DataFrame '{key}' ficou vazio após filtrar colunas")
                    continue
                
                # Verificar se temos as colunas obrigatórias
                if 'cnpj' not in df.columns or 'codigo_produto' not in df.columns:
                    self.logger.error(f"Colunas obrigatórias (cnpj, codigo_produto) não encontradas após filtro")
                    continue
                
                # Colunas de conflito (chave única)
                conflict_cols = ['cnpj', 'codigo_produto']
                
                # ✅ REMOVER DUPLICATAS baseado na chave única
                df = self._remove_duplicates(df, conflict_cols)
                
                if df.empty:
                    self.logger.warning(f"DataFrame '{key}' ficou vazio após remover duplicatas")
                    continue
                
                # ✅ TRUNCAR COLUNAS DE TEXTO que excedem o limite
                df = self._truncate_string_columns(df, table_name)
                
                # Colunas para atualizar (todas exceto as de conflito)
                update_cols = [c for c in df.columns if c not in conflict_cols]
                
                if not update_cols:
                    self.logger.warning(f"Nenhuma coluna para atualizar em {table_name}")
                    continue
                
                # Executar UPSERT
                count = self.upsert_dataframe_psycopg2(
                    table_name=table_name,
                    df=df,
                    conflict_cols=conflict_cols,
                    update_cols=update_cols
                )
                
                total_processed += count
            
            # Commit de todas as transações
            self.connection.commit()
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"✓ Total processado: {total_processed} registros")
            
            message = f"✓ {total_processed} registros processados com sucesso para CNPJ {cnpj}!"
            return True, message
            
        except Exception as e:
            self.logger.error(f"Erro ao processar dados: {e}")
            if self.connection:
                self.connection.rollback()
            
            import traceback
            self.logger.error(traceback.format_exc())
            
            return False, f"Erro: {str(e)}"
    
    def read_tmp_tables_to_dataframes(self, cnpj: str) -> Dict[str, pd.DataFrame]:
        """
        Lê dados das tabelas TMP do PostgreSQL para enviar ao Oracle
        
        BUSCAR: PostgreSQL TMPs → Oracle TMPs
        ✅ COM filtro de CNPJ - busca apenas dados daquele cliente
        
        Args:
            cnpj: CNPJ do cliente
            
        Returns:
            Dict com 4 DataFrames das tabelas TMP
        """
        try:
            if not self.connection:
                self.connect()
            
            self.logger.info(f"Lendo tabelas TMP do OrionTax para CNPJ: {cnpj}")
            
            # 1. ICMS ENTRADA
            self.logger.info("Lendo MXF_TMP_ICMS_ENTRADA...")
            df_icms_entrada = pd.read_sql("""
                SELECT * FROM MXF_TMP_ICMS_ENTRADA WHERE CNPJ = %s
            """, self.connection, params=(cnpj,))
            self.logger.info(f"✓ ICMS Entrada: {len(df_icms_entrada)} registros")
            
            # 2. ICMS SAÍDA
            self.logger.info("Lendo MXF_TMP_ICMS_SAIDA...")
            df_icms_saida = pd.read_sql("""
                SELECT * FROM MXF_TMP_ICMS_SAIDA WHERE CNPJ = %s
            """, self.connection, params=(cnpj,))
            self.logger.info(f"✓ ICMS Saída: {len(df_icms_saida)} registros")
            
            # 3. PIS/COFINS
            self.logger.info("Lendo MXF_TMP_PIS_COFINS...")
            df_pis_cofins = pd.read_sql("""
                SELECT * FROM MXF_TMP_PIS_COFINS WHERE CNPJ = %s
            """, self.connection, params=(cnpj,))
            self.logger.info(f"✓ PIS/COFINS: {len(df_pis_cofins)} registros")
            
            # 4. CBS/IBS
            self.logger.info("Lendo MXF_TMP_CBS_IBS...")
            df_cbs_ibs = pd.read_sql("""
                SELECT * FROM MXF_TMP_CBS_IBS WHERE CNPJ = %s
            """, self.connection, params=(cnpj,))
            self.logger.info(f"✓ CBS/IBS: {len(df_cbs_ibs)} registros")
            
            return {
                'icms_entrada': df_icms_entrada,
                'icms_saida': df_icms_saida,
                'pis_cofins': df_pis_cofins,
                'cbs_ibs': df_cbs_ibs
            }
            
        except Exception as e:
            self.logger.error(f"Erro ao ler tabelas TMP: {e}")
            raise
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
