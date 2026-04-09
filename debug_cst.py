"""
Script de diagnóstico: verifica como os campos CST são lidos do PostgreSQL
e o que seria gravado no Oracle/Firebird.

Uso:
    python debug_cst.py <CNPJ>

Gera: debug_cst_<CNPJ>.txt
"""
import sys
import os
import psycopg2
import pandas as pd
from datetime import datetime

# Adiciona o projeto ao path
sys.path.insert(0, os.path.dirname(__file__))

from config.database import db_manager


def main():
    cnpj = sys.argv[1] if len(sys.argv) > 1 else None
    if not cnpj:
        print("Uso: python debug_cst.py <CNPJ>")
        sys.exit(1)

    output_lines = []

    def log(msg=""):
        print(msg)
        output_lines.append(msg)

    log(f"=== DIAGNOSTICO CST - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    log(f"CNPJ: {cnpj}")
    log()

    log("Conectando em 172.16.10.248:15433/integrador...")

    conn = psycopg2.connect(
        host='172.16.10.248',
        port=15433,
        dbname='integrador',
        user='oriontax_user',
        password='SenhaForte123!@#',
    )
    log("Conexao OK")
    log()

    # Foca em CBS_IBS que é onde o problema ocorre
    log("--- MXF_TMP_CBS_IBS ---")

    cursor = conn.cursor()
    cursor.execute("SELECT * FROM MXF_TMP_CBS_IBS WHERE CNPJ = %s", (cnpj,))
    pg_columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    cursor.close()
    df = pd.DataFrame(rows, columns=pg_columns)

    log(f"  Total registros: {len(df)}")
    log(f"  Valores distintos em cst_cbs_ibs: {sorted(df['cst_cbs_ibs'].unique().tolist())}")
    log(f"  Tipo da coluna no DataFrame: {df['cst_cbs_ibs'].dtype}")
    log()

    # Simula _normalize_dataframe_for_oracle
    log("--- Apos _normalize_dataframe_for_oracle ---")
    df_norm = df.copy()
    df_norm.columns = [c.upper() for c in df_norm.columns]

    for col in df_norm.columns:
        if "DATA" in col or col.startswith("DT_"):
            df_norm[col] = pd.to_datetime(df_norm[col], errors="coerce")
        elif df_norm[col].dtype == object:
            df_norm[col] = (
                df_norm[col]
                .astype(str)
                .str.replace(",", ".", regex=False)
                .replace({"": None, "nan": None, "NaN": None})
            )

    log(f"  Valores de CST_CBS_IBS apos normalize: {sorted(df_norm['CST_CBS_IBS'].unique().tolist())}")
    log(f"  Tipo: {df_norm['CST_CBS_IBS'].dtype}")
    log()

    # Simula clean_value
    TABLE_NUMBER_COLUMNS_CBS = {"ALQ_CBS", "RBC_CBS", "ALQ_IBS", "RBC_IBS",
                                "ALQ_IBS_MUN", "RBC_IBS_MUN", "ALQ_IS", "ALQ_IS_ESPEC"}

    def clean_value_sim(value, col_name):
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        if isinstance(value, str):
            v = value.strip()
            if v.lower() in ("none", "null", "", "nan", "nat", "na", "<na>"):
                return None
            if col_name in TABLE_NUMBER_COLUMNS_CBS:
                try:
                    return float(v.replace(",", "."))
                except ValueError:
                    return None
            return v
        if col_name in TABLE_NUMBER_COLUMNS_CBS:
            try:
                return float(value)
            except Exception:
                return None
        if hasattr(value, 'item'):
            return value.item()
        return value

    log("--- Apos clean_value (simulado) ---")
    valores_cst = df_norm['CST_CBS_IBS'].tolist()
    apos_clean = [clean_value_sim(v, 'CST_CBS_IBS') for v in valores_cst]
    distintos = sorted(set((str(v), type(v).__name__) for v in apos_clean))
    log(f"  Valores que seriam inseridos no Oracle: {distintos}")
    log()

    conn.close()

    # Salvar resultado em arquivo
    output_file = f"debug_cst_{cnpj}.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))

    log(f"Relatorio salvo em: {output_file}")


if __name__ == "__main__":
    main()
