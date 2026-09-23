"""Acesso ao PostgreSQL de integração da Sysmo."""
import logging
from typing import Dict, List

from .mapper import api_product_to_sysmo


SOURCE_COLUMNS = [
    "cd_sequencial", "cd_produto", "tx_codigobarras", "tx_descricaoproduto",
    "tx_ncm", "tx_cest", "nr_cfop", "nr_cst_icms", "vl_aliquota_integral_icms",
    "vl_aliquota_final_icms", "vl_aliquota_fcp", "tx_cbenef", "nr_cst_pis",
    "vl_aliquota_pis", "nr_cst_cofins", "vl_aliquota_cofins",
    "nr_naturezareceita", "tx_estadoorigem", "tx_estadodestino",
]

TARGET_COLUMNS = [
    "cd_sequencial", "cd_produto", "tx_codigobarras", "tx_descricaoproduto",
    "tx_ncm", "tx_cest", "nr_cfop", "nr_cst_icms", "vl_aliquota_integral_icms",
    "vl_aliquota_final_icms", "vl_aliquota_fcp", "tx_cbenef", "nr_cst_pis",
    "vl_aliquota_pis", "nr_cst_cofins", "vl_aliquota_cofins",
    "nr_naturezareceita", "tx_estadoorigem", "tx_estadodestino", "fl_recebido",
]


class SysmoRepository:
    def __init__(self, config: Dict):
        self.config = config
        self.connection = None
        self.logger = logging.getLogger(__name__)

    def connect(self):
        import psycopg2
        self.connection = psycopg2.connect(
            host=self.config["host"], port=self.config.get("port", 5432),
            database=self.config["database_name"], user=self.config["username"],
            password=self.config["password"], connect_timeout=int(self.config.get("timeout_seconds", 15)),
            sslmode=self.config.get("sslmode", "prefer"),
        )
        return self.connection

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def cancel(self):
        if self.connection:
            self.connection.cancel()

    def test_connection(self):
        try:
            self.connect()
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT current_database(), version()")
                database, version = cursor.fetchone()
                cursor.execute("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name IN ('tb_sysmointegradorenvio', 'tb_sysmointegradorrecebimento')
                """)
                tables = {row[0] for row in cursor.fetchall()}
            missing = {"tb_sysmointegradorenvio", "tb_sysmointegradorrecebimento"} - tables
            if missing:
                return False, f"Tabelas Sysmo ausentes: {', '.join(sorted(missing))}"
            return True, f"Conexão Sysmo bem-sucedida: {database}\n{version}"
        except Exception as exc:
            return False, f"Erro: {exc}"
        finally:
            self.close()

    def read_products(self) -> List[dict]:
        if not self.connection:
            self.connect()
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(SOURCE_COLUMNS)} FROM tb_sysmointegradorenvio ORDER BY cd_sequencial ASC"
            )
            return [dict(zip(SOURCE_COLUMNS, row)) for row in cursor.fetchall()]

    def replace_received_products(self, products: List[dict]) -> int:
        if not products:
            raise ValueError("A API retornou uma fotografia vazia; a tabela Sysmo foi preservada.")
        if not self.connection:
            self.connect()
        from psycopg2.extras import execute_values
        # A API V2 atual não documenta `sequencial` na saída. Preservamos o
        # identificador Sysmo pela chave funcional cd_produto.
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT cd_produto, cd_sequencial FROM tb_sysmointegradorenvio")
            sequence_by_code = {str(code).strip(): sequence for code, sequence in cursor.fetchall()}
        missing_sequences = []
        for product in products:
            code = str(product.get("codigo", "")).strip()
            if product.get("sequencial") in (None, 0, ""):
                product["sequencial"] = sequence_by_code.get(code)
            if product.get("sequencial") in (None, ""):
                missing_sequences.append(code)
        if missing_sequences:
            sample = ", ".join(missing_sequences[:10])
            raise ValueError(f"Produtos sem sequencial Sysmo ({len(missing_sequences)}): {sample}")
        rows = [api_product_to_sysmo(item) for item in products]
        placeholders = ", ".join(TARGET_COLUMNS)
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("DELETE FROM tb_sysmointegradorrecebimento")
                execute_values(
                    cursor,
                    f"INSERT INTO tb_sysmointegradorrecebimento ({placeholders}) VALUES %s",
                    rows,
                    page_size=1000,
                )
            self.connection.commit()
            return len(rows)
        except Exception:
            self.connection.rollback()
            raise
