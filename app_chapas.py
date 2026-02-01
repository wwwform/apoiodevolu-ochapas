import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import os
import io

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Sistema Chapas", layout="wide")

# --- CSS NUCLEAR ---
st.markdown("""
<style>
    header[data-testid="stHeader"] {visibility: hidden; display: none;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden; display: none;}
    [data-testid="stDecoration"] {visibility: hidden; display: none;}
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
    .stInfo {
        font-size: 1.2rem;
        font-weight: bold;
    }
    .block-container {
        padding-top: 1rem !important;
    }
</style>
""", unsafe_allow_html=True)

# --- CONEXÃO GOOGLE SHEETS ---
@st.cache_resource
def conectar_google():
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        client = gspread.authorize(creds)
        return client.open("BD_Fabrica_Geral")
    except Exception as e: return None

def garantir_cabecalhos():
    sh = conectar_google()
    if sh is None: return
    try:
        try: ws_prod = sh.worksheet("Chapas_Producao")
        except: ws_prod = sh.add_worksheet(title="Chapas_Producao", rows=1000, cols=20)
        if not ws_prod.row_values(1):
            ws_prod.append_row(["id", "data_hora", "lote", "reserva", "status_reserva", "cod_sap", "descricao", "qtd", "peso_real", "largura_real_mm", "largura_corte_mm", "tamanho_real_mm", "tamanho_corte_mm", "peso_teorico", "sucata"])
        
        try: ws_lotes = sh.worksheet("Chapas_Lotes")
        except: ws_lotes = sh.add_worksheet(title="Chapas_Lotes", rows=1000, cols=5)
        if not ws_lotes.row_values(1):
            ws_lotes.append_row(["cod_sap", "ultimo_numero"])
    except: pass

garantir_cabecalhos()

# --- CORREÇÃO DE NÚMEROS (PONTO/VÍRGULA) ---
def limpar_numero_sap(valor):
    """Garante que '392,5' (Texto) vire 392.5 (Float)"""
    if pd.isna(valor): return 0.0
    s = str(valor).strip()
    if not s: return 0.0
    if isinstance(valor, (int, float)): return float(valor)
    s = s.replace(',', '.')
    try: return float(s)
    except: return 0.0

def formatar_br(valor):
    """Garante saída com vírgula e 3 casas"""
    try:
        val = float(valor)
        return f"{val:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,000"

def regra_multiplos_300_baixo(mm):
    try: return (int(float(mm)) // 300) * 300
    except: return 0

# --- CARREGAMENTO DO ARQUIVO ---
@st.cache_data
def carregar_base_sap():
    caminho = None
    if os.path.exists("base_sap.xlsx"): caminho = "base_sap.xlsx"
    else:
        pasta = os.path.dirname(os.path.abspath(__file__))
        for f in os.listdir(pasta):
            if f.lower() == "base_sap.xlsx":
                caminho = os.path.join(pasta, f)
                break
    
    if not caminho: return None

    try:
        df = pd.read_excel(caminho)
        df.columns = df.columns.str.strip()
        df['Produto'] = pd.to_numeric(df['Produto'], errors='coerce').fillna(0).astype(int)
        
        # APLICA A CORREÇÃO NO FATOR AQUI
        if 'Peso por Metro' in df.columns:
            df['Peso por Metro'] = df['Peso por Metro'].apply(limpar_numero_sap)
            
        return df
    except: return None

# --- FUNÇÕES ---
def ler_banco():
    sh = conectar_google()
    ws = sh.worksheet("Chapas_Producao")
    df = pd.DataFrame(ws.get_all_records())
    cols_num = ['id', 'cod_sap', 'qtd', 'peso_real', 'largura_real_mm', 'largura_corte_mm', 'tamanho_real_mm', 'tamanho_corte_mm', 'peso_teorico', 'sucata']
    for c in cols_num:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    return df.sort_values(by='id', ascending=False)

def obter_e_incrementar_lote(cod_sap):
    sh = conectar_google()
    ws = sh.worksheet("Chapas_Lotes")
    try:
        cell = ws.find(str(cod_sap))
        ultimo = int(ws.cell(cell.row, 2).value)
        proximo = ultimo + 1
        ws.update_cell(cell.row, 2, proximo)
    except:
        proximo = 1
        ws.append_row([cod_sap, proximo])
    return f"BRASA{proximo:05d}"

def salvar_no_banco(dados):
    sh = conectar_google()
    ws = sh.worksheet("Chapas_Producao")
    lote = obter_e_incrementar_lote(dados['Cód. SAP'])
    novo_id = int(datetime.now().timestamp() * 1000)
    linha = [
        novo_id, datetime.now().strftime("%d/%m/%Y %H:%M:%S"), lote,
        dados['Reserva'], "Pendente", int(dados['Cód. SAP']), dados['Descrição'],
        int(dados['Qtd']), float(dados['Peso Balança (kg)']), int(dados['Largura Real (mm)']),
        int(dados['Largura Corte (mm)']), int(dados['Tamanho Real (mm)']),
        int(dados['Tamanho Corte (mm)']), float(dados['Peso Teórico']), float(dados['Sucata'])
    ]
    ws.append_row(linha)
    return lote

def atualizar_status_lote(df_editado):
    sh = conectar_google()
    ws = sh.worksheet("Chapas_Producao")
    registros = ws.get_all_records()
    for i, row in enumerate(registros):
        id_row = row['id']
        editado = df_editado[df_editado['id'] == id_row]
        if not editado.empty:
            novo = editado.iloc[0]['status_reserva']
            if row['status_reserva'] != novo:
                ws.update_cell(i+2, 5, novo)

def limpar_banco_completo():
    sh = conectar_google()
    sh.worksheet("Chapas_Producao").clear()
    sh.worksheet("Chapas_Producao").append_row(["id", "data_hora", "lote", "reserva", "status_reserva", "cod_sap", "descricao", "qtd", "peso_real", "largura_real_mm", "largura_corte_mm", "tamanho_real_mm", "tamanho_corte_mm", "peso_teorico", "sucata"])
    sh.worksheet("Chapas_Lotes").clear()
    sh.worksheet("Chapas_Lotes").append_row(["cod_sap", "ultimo_numero"])

def excluir_linha_por_id(id_alvo):
    sh = conectar_google()
    ws = sh.worksheet("Chapas_Producao")
    try:
        cell = ws.find(str(id_alvo))
        ws.delete_rows(cell.row)
        return True
    except: return False

def ajustar_contador_lote(cod_sap, novo_valor):
    sh = conectar_google()
    ws = sh.worksheet("Chapas_Lotes")
    try:
        cell = ws.find(str(cod_sap))
        ws.update_cell(cell.row, 2, novo_valor)
    except:
        ws.append_row([cod_sap, novo_valor])

# --- APP ---
df_sap = carregar_base_sap()
if df_sap is None: st.error("ERRO: base_sap.xlsx não encontrado.")

st.sidebar.title("🔐 Acesso Chapas")
modo_acesso = st.sidebar.radio("Perfil:", ["Operador (Chão de Fábrica)", "Administrador (Escritório)", "Super Admin"])

if modo_acesso == "Operador (Chão de Fábrica)":
    st.title("🏭 Chapas: Bipagem")
    if df_sap is not None:
        if 'wizard_data' not in st.session_state: st.session_state.wizard_data = {}
        if 'wizard_step' not in st.session_state: st.session_state.wizard_step = 0
        
        @st.dialog("📦 Entrada")
        def wizard():
            st.write(f"**Item:** {st.session_state.wizard_data.get('Cód. SAP')} - {st.session_state.wizard_data.get('Descrição')}")
            st.markdown("---")
            if st.session_state.wizard_step == 1:
                with st.form("f1"):
                    res = st.text_input("1. Reserva:", key="w_res")
                    if st.form_submit_button("PRÓXIMO >>", type="primary"):
                        if res.strip():
                            st.session_state.wizard_data['Reserva'] = res
                            st.session_state.wizard_step = 2
                            st.rerun()
                        else: st.error("Obrigatório")
            elif st.session_state.wizard_step == 2:
                with st.form("f2"):
                    qtd = st.number_input("2. Qtd (Peças):", min_value=1, step=1)
                    if st.form_submit_button("PRÓXIMO >>", type="primary"):
                        st.session_state.wizard_data['Qtd'] = qtd
                        st.session_state.wizard_step = 3
                        st.rerun()
            elif st.session_state.wizard_step == 3:
                with st.form("f3"):
                    peso = st.number_input("3. Peso Real (kg):", min_value=0.001, format="%.3f")
                    if st.form_submit_button("PRÓXIMO >>", type="primary"):
                        st.session_state.wizard_data['Peso Balança (kg)'] = peso
                        st.session_state.wizard_step = 4
                        st.rerun()
            elif st.session_state.wizard_step == 4:
                with st.form("f4"):
                    larg = st.number_input("4. Largura Real (mm):", min_value=0)
                    if larg > 0: st.caption(f"Regra 300mm: {larg} -> {regra_multiplos_300_baixo(larg)}")
                    if st.form_submit_button("PRÓXIMO >>", type="primary"):
                        st.session_state.wizard_data['Largura Real (mm)'] = larg
                        st.session_state.wizard_step = 5
                        st.rerun()
            elif st.session_state.wizard_step == 5:
                with st.form("f5"):
                    comp = st.number_input("5. Comp. Real (mm):", min_value=0)
                    if comp > 0: st.caption(f"Regra 300mm: {comp} -> {regra_multiplos_300_baixo(comp)}")
                    if st.form_submit_button("✅ SALVAR", type="primary"):
                        if comp > 0:
                            with st.spinner("Salvando..."):
                                fsap = st.session_state.wizard_data['Fator SAP']
                                qtd = st.session_state.wizard_data['Qtd']
                                pr = st.session_state.wizard_data['Peso Balança (kg)']
                                lr = st.session_state.wizard_data['Largura Real (mm)']
                                lc = regra_multiplos_300_baixo(lr)
                                tc = regra_multiplos_300_baixo(comp)
                                
                                # Cálculo corrigido com Fator em Float (392.5)
                                pt = fsap * (lc/1000.0) * (tc/1000.0) * qtd
                                suc = pr - pt
                                
                                dados = {
                                    "Reserva": st.session_state.wizard_data['Reserva'],
                                    "Cód. SAP": st.session_state.wizard_data['Cód. SAP'],
                                    "Descrição": st.session_state.wizard_data['Descrição'],
                                    "Qtd": qtd, "Peso Balança (kg)": pr,
                                    "Largura Real (mm)": lr, "Largura Corte (mm)": lc,
                                    "Tamanho Real (mm)": comp, "Tamanho Corte (mm)": tc,
                                    "Peso Teórico": pt, "Sucata": suc
                                }
                                lote = salvar_no_banco(dados)
                                st.toast(f"Chapa Salva! Lote: {lote}", icon="🏗️")
                                st.session_state.wizard_data = {}
                                st.session_state.wizard_step = 0
                                st.session_state.input_scanner = ""
                                time.sleep(1)
                                st.rerun()
                        else: st.error("Comp inválido")

        def check_scan():
            cod = st.session_state.input_scanner
            if cod:
                try:
                    cod_limpo = int(str(cod).strip().split(":")[-1])
                    prod = df_sap[df_sap['Produto'] == cod_limpo]
                    if not prod.empty:
                        st.session_state.wizard_data = {
                            "Cód. SAP": cod_limpo,
                            "Descrição": prod.iloc[0]['Descrição do produto'],
                            "Fator SAP": prod.iloc[0]['Peso por Metro']
                        }
                        st.session_state.wizard_step = 1
                    else: st.toast("Material não encontrado", icon="🚫")
                except: st.session_state.input_scanner = ""

        if st.session_state.wizard_step > 0: wizard()
        st.text_input("BIPAR CÓDIGO CHAPA:", key="input_scanner", on_change=check_scan)

elif modo_acesso == "Administrador (Escritório)":
    st.title("💻 Admin (Google Cloud)")
    if st.sidebar.text_input("Senha", type="password") == "Br@met4lChapas":
        st.success("Logado")
        try: df = ler_banco()
        except: df = pd.DataFrame()
        
        if not df.empty:
            t1, t2 = st.tabs(["Tabela", "KPIs"])
            with t1:
                if st.button("Atualizar"): st.rerun()
                c1,c2,c3 = st.columns(3)
                c1.metric("Itens", len(df))
                c2.metric("Total (kg)", formatar_br(df['peso_real'].sum()))
                c3.metric("Sucata (kg)", formatar_br(df['sucata'].sum()))
                
                ed = st.data_editor(df, use_container_width=True, key="ed_chapas", column_config={
                    "id": st.column_config.NumberColumn(disabled=True),
                    "status_reserva": st.column_config.SelectboxColumn("Status", options=["Pendente", "Ok - Lançada"], required=True)
                })
                if st.button("Salvar Status"):
                    with st.spinner("..."): atualizar_status_lote(ed)
                    st.success("Salvo!")
                    st.rerun()
                
                # Export
                lst = []
                for _, r in df.iterrows():
                    lst.append({'Lote': r['lote'], 'Reserva': r['reserva'], 'SAP': r['cod_sap'], 'Descrição': r['descricao'], 'Status': r['status_reserva'], 'Qtd': r['qtd'], 'Peso Lançamento (kg)': formatar_br(r['peso_teorico']), 'Largura Real': r['largura_real_mm'], 'Largura Consid.': r['largura_corte_mm'], 'Comp. Real': r['tamanho_real_mm'], 'Comp. Consid.': r['tamanho_corte_mm']})
                    if r['sucata'] > 0.001:
                        lst.append({'Lote': 'VIRTUAL', 'Reserva': r['reserva'], 'SAP': r['cod_sap'], 'Descrição': f"SUCATA - {r['descricao']}", 'Status': r['status_reserva'], 'Qtd': 1, 'Peso Lançamento (kg)': formatar_br(r['sucata']), 'Largura Real': 0, 'Largura Consid.': 0, 'Comp. Real': 0, 'Comp. Consid.': 0})
                
                df_exp = pd.DataFrame(lst)
                if not df_exp.empty:
                    cols_final = [c for c in ['Lote', 'Reserva', 'SAP', 'Descrição', 'Peso Lançamento (kg)', 'Status', 'Qtd', 'Largura Real', 'Largura Consid.', 'Comp. Real', 'Comp. Consid.'] if c in df_exp.columns]
                    df_exp = df_exp[cols_final]
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as writer: df_exp.to_excel(writer, index=False)
                    st.download_button("Baixar Excel", buf.getvalue(), "Relatorio_Chapas.xlsx", "primary")
            
            with t2:
                pt = df['peso_real'].sum()
                stt = df['sucata'].sum()
                idx = (stt/pt)*100 if pt>0 else 0
                k1,k2,k3 = st.columns(3)
                k1.metric("Produção", f"{pt:,.2f}")
                k2.metric("Sucata", f"{stt:,.2f}")
                k3.metric("Índice", f"{idx:.2f}%")
                st.bar_chart(df.groupby("descricao")["peso_real"].sum().sort_values(ascending=False).head(10))
        else: st.info("Vazio")
    else: st.sidebar.error("Senha incorreta")

elif modo_acesso == "Super Admin":
    st.title("🛠️ Super Admin")
    if st.sidebar.text_input("Senha Mestra", type="password") == "Workaround&97146605":
        st.success("ROOT")
        if st.button("💣 ZERAR PLANILHA", type="primary"):
            limpar_banco_completo()
            st.success("Zerado!")
        
        st.write("---")
        st.write("Lotes:")
        st.dataframe(pd.DataFrame(conectar_google().worksheet("Chapas_Lotes").get_all_records()))
        c1, c2 = st.columns(2)
        sap = c1.number_input("SAP", step=1)
        val = c2.number_input("Novo Valor", step=1)
        if st.button("Ajustar Lote"):
            ajustar_contador_lote(sap, val)
            st.success("Feito")
            
        st.write("---")
        st.write("Excluir ID:")
        st.dataframe(ler_banco())
        idd = st.number_input("ID", step=1)
        if st.button("Excluir"):
            excluir_linha_por_id(idd)
            st.success("Feito")
            st.rerun()
