import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import time
import os
import io

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Sistema Chapas", layout="wide")

# --- CSS NUCLEAR ---
st.markdown("""
<style>
    header[data-testid="stHeader"] {display: none;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display:none;}
    div[data-testid="stTextInput"] label, div[data-testid="stNumberInput"] label {
        font-size: 1.5rem !important;
        font-weight: bold;
        color: #d97706; 
    }
    .stButton>button {
        height: 3.5rem;
        font-size: 1.2rem !important;
        font-weight: bold;
    }
    .block-container {padding-top: 1rem !important;}
</style>
""", unsafe_allow_html=True)

# --- BANCO DE DADOS (SQLite) ---
DB_FILE = "dados_chapas.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS producao 
                 (id INTEGER PRIMARY KEY, data_hora TEXT, lote TEXT, reserva TEXT, 
                  status_reserva TEXT, cod_sap INTEGER, descricao TEXT, qtd INTEGER, 
                  peso_real REAL, largura_real_mm INTEGER, largura_corte_mm INTEGER, 
                  tamanho_real_mm INTEGER, tamanho_corte_mm INTEGER, 
                  peso_teorico REAL, sucata REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS lotes 
                 (cod_sap INTEGER PRIMARY KEY, ultimo_numero INTEGER)''')
    conn.commit()
    conn.close()

init_db()

# --- FUNÇÕES ---
def get_next_lote(cod_sap):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT ultimo_numero FROM lotes WHERE cod_sap = ?", (cod_sap,))
    row = c.fetchone()
    if row:
        prox = row[0] + 1
    else:
        prox = 1
    
    c.execute("INSERT OR REPLACE INTO lotes (cod_sap, ultimo_numero) VALUES (?, ?)", (cod_sap, prox))
    conn.commit()
    conn.close()
    return f"BRASA{prox:05d}"

def salvar_producao(dados):
    lote = get_next_lote(dados['cod_sap'])
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""INSERT INTO producao (data_hora, lote, reserva, status_reserva, cod_sap, 
                 descricao, qtd, peso_real, largura_real_mm, largura_corte_mm, 
                 tamanho_real_mm, tamanho_corte_mm, peso_teorico, sucata)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (datetime.now().strftime("%d/%m/%Y %H:%M:%S"), lote, dados['reserva'], 
               "Pendente", dados['cod_sap'], dados['descricao'], dados['qtd'], 
               dados['peso_real'], dados['largura_real_mm'], dados['largura_corte_mm'],
               dados['tamanho_real_mm'], dados['tamanho_corte_mm'], 
               dados['peso_teorico'], dados['sucata']))
    conn.commit()
    conn.close()
    return lote

def formatar_br(v):
    try: return f"{float(v):,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,000"

def regra_300(mm):
    try: return (int(float(mm)) // 300) * 300
    except: return 0

def limpar_numero_sap(valor):
    if pd.isna(valor): return 0.0
    if isinstance(valor, (int, float)): return float(valor)
    s = str(valor).strip()
    if '.' in s and ',' in s: s = s.replace('.', '')
    s = s.replace(',', '.')
    try: return float(s)
    except: return 0.0

@st.cache_data
def carregar_base_sap():
    path = "base_sap.xlsx"
    if not os.path.exists(path): return None
    try:
        df = pd.read_excel(path)
        df.columns = df.columns.str.strip().str.upper()
        col_prod = next((c for c in df.columns if 'PRODUTO' in c), None)
        col_peso = next((c for c in df.columns if 'PESO' in c and 'METRO' in c), None)
        if col_prod and col_peso:
            df['PRODUTO'] = pd.to_numeric(df[col_prod], errors='coerce').fillna(0).astype(int)
            df['PESO_FATOR'] = df[col_peso].apply(limpar_numero_sap)
            return df
        return None
    except: return None

# --- APP ---
st.sidebar.title("🔐 Acesso Restrito")
perfil = st.sidebar.radio("Perfil:", ["Operador (Chão de Fábrica)", "Administrador (Escritório)", "Super Admin"])
df_sap = carregar_base_sap()

if perfil == "Operador (Chão de Fábrica)":
    st.title("🏭 Chapas: Bipagem")
    if df_sap is not None:
        if 'wizard_data' not in st.session_state: st.session_state.wizard_data = {}
        if 'wizard_step' not in st.session_state: st.session_state.wizard_step = 0
        
        @st.dialog("📦 Entrada")
        def wizard():
            st.write(f"**Item:** {st.session_state.wizard_data.get('Cód. SAP')} - {st.session_state.wizard_data.get('Descrição')}")
            fator_real = st.number_input("Fator SAP (kg/m²):", value=float(st.session_state.wizard_data.get('PESO_FATOR', 0.0)), format="%.4f")
            
            st.markdown("---")
            if st.session_state.wizard_step == 1:
                with st.form("f1"):
                    res = st.text_input("1. Reserva:", key="w_res")
                    if st.form_submit_button("PRÓXIMO"):
                        if res.strip():
                            st.session_state.wizard_data['Reserva'] = res
                            st.session_state.wizard_data['PESO_FATOR'] = fator_real
                            st.session_state.wizard_step = 2
                            st.rerun()
                        else: st.error("Obrigatório")
            elif st.session_state.wizard_step == 2:
                with st.form("f2"):
                    qtd = st.number_input("2. Qtd:", min_value=1, step=1)
                    if st.form_submit_button("PRÓXIMO"):
                        st.session_state.wizard_data['Qtd'] = qtd
                        st.session_state.wizard_step = 3
                        st.rerun()
            elif st.session_state.wizard_step == 3:
                with st.form("f3"):
                    peso = st.number_input("3. Peso Real (kg):", min_value=0.001, format="%.3f")
                    if st.form_submit_button("PRÓXIMO"):
                        st.session_state.wizard_data['Peso Balança (kg)'] = peso
                        st.session_state.wizard_step = 4
                        st.rerun()
            elif st.session_state.wizard_step == 4:
                with st.form("f4"):
                    larg = st.number_input("4. Largura (mm):", min_value=0)
                    if st.form_submit_button("PRÓXIMO"):
                        st.session_state.wizard_data['Largura Real (mm)'] = larg
                        st.session_state.wizard_step = 5
                        st.rerun()
            elif st.session_state.wizard_step == 5:
                comp = st.number_input("5. Comp. Real (mm):", min_value=0)
                
                fator = st.session_state.wizard_data['PESO_FATOR']
                q = st.session_state.wizard_data['Qtd']
                larg_real = st.session_state.wizard_data['Largura Real (mm)']
                lc = regra_300(larg_real)
                tc = regra_300(comp)
                peso_teorico_prev = fator * (lc/1000.0) * (tc/1000.0) * q
                
                if comp > 0: st.info(f"Calc: **{formatar_br(peso_teorico_prev)} kg**")
                
                if st.button("✅ SALVAR"):
                    if comp > 0:
                        pr = st.session_state.wizard_data['Peso Balança (kg)']
                        suc = pr - peso_teorico_prev
                        
                        dados = {
                            "reserva": st.session_state.wizard_data['Reserva'],
                            "cod_sap": int(st.session_state.wizard_data['Cód. SAP']),
                            "descricao": st.session_state.wizard_data['Descrição'],
                            "qtd": int(q),
                            "peso_real": float(pr),
                            "largura_real_mm": int(larg_real),
                            "largura_corte_mm": int(lc),
                            "tamanho_real_mm": int(comp),
                            "tamanho_corte_mm": int(tc),
                            "peso_teorico": float(peso_teorico_prev),
                            "sucata": float(suc)
                        }
                        
                        lote = salvar_producao(dados)
                        st.toast(f"Lote {lote} Salvo!", icon="✅")
                        st.session_state.wizard_step = 0
                        st.session_state.input_scanner = ""
                        time.sleep(1)
                        st.rerun()
                    else: st.error("Inválido")

        def check_scan():
            cod = st.session_state.input_scanner
            if cod:
                try:
                    cod_limpo = int(str(cod).strip().split(":")[-1])
                    prod = df_sap[df_sap['PRODUTO'] == cod_limpo]
                    if not prod.empty:
                        st.session_state.wizard_data = {
                            "Cód. SAP": cod_limpo,
                            "Descrição": prod.iloc[0]['DESCRIÇÃO DO PRODUTO'],
                            "PESO_FATOR": prod.iloc[0]['PESO_FATOR']
                        }
                        st.session_state.wizard_step = 1
                    else: st.toast("Não encontrado")
                except: pass
                st.session_state.input_scanner = ""

        if st.session_state.wizard_step > 0: wizard()
        st.text_input("BIPAR:", key="input_scanner", on_change=check_scan)

# === ADMIN ===
elif perfil == "Administrador (Escritório)":
    st.title("💻 Admin")
    if st.sidebar.text_input("Senha", type="password") == "Br@met4lChapas":
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query("SELECT * FROM producao ORDER BY id DESC", conn)
        conn.close()
        
        if not df.empty:
            t1, t2 = st.tabs(["Tabela", "KPIs"])
            with t1:
                if st.button("Atualizar"): st.rerun()
                c1,c2,c3 = st.columns(3)
                c1.metric("Itens", len(df))
                c2.metric("Total", formatar_br(df['peso_real'].sum()))
                c3.metric("Sucata", formatar_br(df['sucata'].sum()))
                
                df_show = st.data_editor(df, key="ed", use_container_width=True, column_config={
                    "id": st.column_config.NumberColumn(disabled=True),
                    "status_reserva": st.column_config.SelectboxColumn("Status", options=["Pendente", "Ok - Lançada"], required=True)
                })
                
                if st.button("Salvar Status"):
                    conn = sqlite3.connect(DB_FILE)
                    c = conn.cursor()
                    for i, r in df_show.iterrows():
                        c.execute("UPDATE producao SET status_reserva = ? WHERE id = ?", (r['status_reserva'], r['id']))
                    conn.commit()
                    conn.close()
                    st.success("Salvo!")
                    st.rerun()
                
                lst = []
                for _, r in df.iterrows():
                    lst.append({
                        'Lote': r['lote'], 'Reserva': r['reserva'], 'SAP': r['cod_sap'],
                        'Descrição': r['descricao'], 'Status': r['status_reserva'],
                        'Qtd': int(r['qtd']),
                        'Peso Lançamento (kg)': float(r['peso_teorico']),
                        'Largura Real': int(r['largura_real_mm']),
                        'Largura Consid.': int(r['largura_corte_mm']),
                        'Comp. Real': int(r['tamanho_real_mm']),
                        'Comp. Consid.': int(r['tamanho_corte_mm'])
                    })
                    if r['sucata'] > 0.001:
                        lst.append({
                            'Lote': 'VIRTUAL', 'Reserva': r['reserva'], 'SAP': r['cod_sap'],
                            'Descrição': f"SUCATA - {r['descricao']}", 'Status': r['status_reserva'],
                            'Qtd': 1, 'Peso Lançamento (kg)': float(r['sucata']),
                            'Largura Real': 0, 'Largura Consid.': 0, 'Comp. Real': 0, 'Comp. Consid.': 0
                        })
                
                df_exp = pd.DataFrame(lst)
                b = io.BytesIO()
                with pd.ExcelWriter(b, engine='openpyxl') as w:
                    df_exp.to_excel(w, index=False, sheet_name='Relatorio')
                    ws = w.sheets['Relatorio']
                    try:
                        idx = df_exp.columns.get_loc('Peso Lançamento (kg)') + 1
                        for row in range(2, ws.max_row + 1):
                            ws.cell(row=row, column=idx).number_format = '#,##0.000'
                    except: pass
                
                st.download_button("Baixar Excel", b.getvalue(), "Relatorio_Chapas.xlsx", "primary")
                
                # BACKUP
                with open(DB_FILE, "rb") as f:
                    st.download_button("💾 Backup Banco (.db)", f, "backup_chapas.db")

            with t2:
                pt = df['peso_real'].sum()
                stt = df['sucata'].sum()
                idx = (stt/pt)*100 if pt>0 else 0
                st.metric("Índice de Sucata", f"{idx:.2f}%")
                st.bar_chart(df.groupby("descricao")["peso_real"].sum().sort_values(ascending=False).head(10))
        else: st.info("Sem dados")
    else: st.error("Senha incorreta")

elif perfil == "Super Admin":
    st.title("🛠️ Super Admin")
    if st.sidebar.text_input("Senha Mestra", type="password") == "Workaround&97146605":
        if st.button("💣 ZERAR BANCO", type="primary"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("DELETE FROM producao")
            c.execute("DELETE FROM lotes")
            conn.commit()
            conn.close()
            st.success("Zerado!")
        
        st.write("---")
        conn = sqlite3.connect(DB_FILE)
        st.write("Lotes")
        st.dataframe(pd.read_sql_query("SELECT * FROM lotes", conn))
        c1, c2 = st.columns(2)
        sap = c1.number_input("SAP", step=1)
        val = c2.number_input("Novo Valor", step=1)
        if st.button("Ajustar"):
            c = conn.cursor()
            c.execute("UPDATE lotes SET ultimo_numero = ? WHERE cod_sap = ?", (val, sap))
            conn.commit()
            st.success("Feito")
            st.rerun()
        
        st.write("---")
        st.write("Excluir ID")
        idd = st.number_input("ID", step=1)
        if st.button("Excluir"):
            c = conn.cursor()
            c.execute("DELETE FROM producao WHERE id = ?", (idd,))
            conn.commit()
            st.success("Feito")
            st.rerun()
        conn.close()
    else: st.error("Negado")
