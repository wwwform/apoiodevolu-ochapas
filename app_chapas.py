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

# --- CSS ---
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

# --- CONEXÃO GOOGLE ---
@st.cache_resource
def conectar_google():
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        client = gspread.authorize(creds)
        return client.open("BD_Fabrica_Geral")
    except: return None

def garantir_cabecalhos():
    sh = conectar_google()
    if not sh: return
    try:
        try: ws = sh.worksheet("Chapas_Producao")
        except: ws = sh.add_worksheet("Chapas_Producao", 1000, 20)
        if not ws.row_values(1): ws.append_row(["id","data_hora","lote","reserva","status_reserva","cod_sap","descricao","qtd","peso_real","largura_real_mm","largura_corte_mm","tamanho_real_mm","tamanho_corte_mm","peso_teorico","sucata"])
        
        try: ws_l = sh.worksheet("Chapas_Lotes")
        except: ws_l = sh.add_worksheet("Chapas_Lotes", 1000, 5)
        if not ws_l.row_values(1): ws_l.append_row(["cod_sap","ultimo_numero"])
    except: pass

garantir_cabecalhos()

# --- FUNÇÕES ---
def normalizar_numero_br(v):
    """Converte valores (string ou numérico) para float puro do Python"""
    if pd.isna(v) or v == "": return 0.0
    if isinstance(v, (int, float)): return float(v)
    try:
        s = str(v).strip()
        # Se tiver vírgula e ponto, assume formato BR (ex: 1.250,50)
        if ',' in s and '.' in s:
            s = s.replace('.', '').replace(',', '.')
        # Se tiver só vírgula, troca por ponto (ex: 70,65)
        elif ',' in s:
            s = s.replace(',', '.')
        return float(s)
    except:
        return 0.0

def formatar_br(v):
    try: return f"{float(v):,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,000"

def regra_300(mm):
    try: return (int(float(mm)) // 300) * 300
    except: return 0

@st.cache_data(ttl=60)
def obter_dados_chapas():
    sh = conectar_google()
    if not sh: return pd.DataFrame()
    try:
        ws = sh.worksheet("Chapas_Producao")
        df = pd.DataFrame(ws.get_all_records())
        return df
    except: return pd.DataFrame()

# --- APP ---
st.sidebar.title("🔐 Acesso")
perfil = st.sidebar.radio("Perfil:", ["Operador (Chão de Fábrica)", "Administrador (Escritório)", "Super Admin"])

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
            df['PESO_FATOR'] = df[col_peso].apply(normalizar_numero_br)
            return df
        return None
    except: return None

df_sap = carregar_base_sap()

if perfil == "Operador (Chão de Fábrica)":
    st.title("🏭 Chapas: Bipagem")
    if df_sap is not None:
        if 'wizard_data' not in st.session_state: st.session_state.wizard_data = {}
        if 'wizard_step' not in st.session_state: st.session_state.wizard_step = 0
        
        @st.dialog("📦 Entrada")
        def wizard():
            st.write(f"**Item:** {st.session_state.wizard_data.get('Cód. SAP')}")
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
                        with st.spinner("Salvando..."):
                            sh = conectar_google()
                            ws_p = sh.worksheet("Chapas_Producao")
                            ws_l = sh.worksheet("Chapas_Lotes")
                            
                            sap = st.session_state.wizard_data['Cód. SAP']
                            try:
                                cell = ws_l.find(str(sap))
                                ult = int(ws_l.cell(cell.row, 2).value)
                                prox = ult + 1
                                ws_l.update_cell(cell.row, 2, prox)
                            except:
                                prox = 1
                                ws_l.append_row([sap, prox])
                            lote = f"BRASA{prox:05d}"
                            
                            pr = st.session_state.wizard_data['Peso Balança (kg)']
                            suc = pr - peso_teorico_prev
                            
                            ws_p.append_row([
                                int(datetime.now().timestamp()*1000),
                                datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                                lote, st.session_state.wizard_data['Reserva'],
                                "Pendente", int(sap), st.session_state.wizard_data['Descrição'],
                                int(q), float(pr), int(larg_real), int(lc),
                                int(comp), int(tc), float(peso_teorico_prev), float(suc)
                            ])
                            st.toast(f"Salvo: {lote}")
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
        if st.button("🔄 Atualizar"):
            obter_dados_chapas.clear()
            st.rerun()
            
        df = obter_dados_chapas()
        
        if not df.empty:
            # Normalizar colunas numéricas vindas do Sheets
            cols_num = ['peso_real', 'sucata', 'peso_teorico', 'qtd']
            for c in cols_num:
                if c in df.columns: 
                    df[c] = df[c].apply(normalizar_numero_br)
            
            c1,c2,c3 = st.columns(3)
            c1.metric("Itens", len(df))
            c2.metric("Total", formatar_br(df['peso_real'].sum()))
            c3.metric("Sucata", formatar_br(df['sucata'].sum()))
            
            df_show = st.data_editor(df, key="ed", use_container_width=True, column_config={
                "id": st.column_config.NumberColumn(disabled=True),
                "status_reserva": st.column_config.SelectboxColumn("Status", options=["Pendente", "Ok - Lançada"], required=True)
            })
            
            if st.button("Salvar Status"):
                sh = conectar_google()
                ws = sh.worksheet("Chapas_Producao")
                for i, r in enumerate(ws.get_all_records()):
                    rid = r['id']
                    row_ed = df_show[df_show['id'] == rid]
                    if not row_ed.empty and r['status_reserva'] != row_ed.iloc[0]['status_reserva']:
                        ws.update_cell(i+2, 5, row_ed.iloc[0]['status_reserva'])
                obter_dados_chapas.clear()
                st.success("Salvo!")
                st.rerun()
            
            # --- PREPARAÇÃO DO EXCEL (ALTERAÇÃO AQUI) ---
            lst = []
            for _, r in df.iterrows():
                lst.append({
                    'Lote': r['lote'], 'Reserva': r['reserva'], 'SAP': r['cod_sap'],
                    'Descrição': r['descricao'], 'Status': r['status_reserva'],
                    'Qtd': int(r['qtd']),
                    'Peso Lançamento (kg)': float(r['peso_teorico']), # Forçado float
                    'Largura Real': int(r['largura_real_mm']),
                    'Largura Consid.': int(r['largura_corte_mm']),
                    'Comp. Real': int(r['tamanho_real_mm']),
                    'Comp. Consid.': int(r['tamanho_corte_mm'])
                })
                if r['sucata'] > 0.001:
                    lst.append({
                        'Lote': 'VIRTUAL', 'Reserva': r['reserva'], 'SAP': r['cod_sap'],
                        'Descrição': f"SUCATA - {r['descricao']}", 'Status': r['status_reserva'],
                        'Qtd': 1, 
                        'Peso Lançamento (kg)': float(r['sucata']), # Forçado float
                        'Largura Real': 0, 'Largura Consid.': 0,
                        'Comp. Real': 0, 'Comp. Consid.': 0
                    })
            
            df_exp = pd.DataFrame(lst)
            
            # Geração do buffer Excel
            b = io.BytesIO()
            with pd.ExcelWriter(b, engine='openpyxl') as w:
                df_exp.to_excel(w, index=False, sheet_name='Relatorio')
                ws_x = w.sheets['Relatorio']
                
                # Garantia de Formatação e Tipo de Célula
                try:
                    col_idx = df_exp.columns.get_loc('Peso Lançamento (kg)') + 1
                    for row_num in range(2, ws_x.max_row + 1):
                        cell = ws_x.cell(row=row_num, column=col_idx)
                        if cell.value is not None:
                            # Re-força o valor como float para o openpyxl
                            cell.value = float(cell.value)
                        # Define formato numérico com 3 casas decimais
                        cell.number_format = '#,##0.000'
                except: pass
            
            st.download_button(
                label="Baixar Excel",
                data=b.getvalue(),
                file_name=f"Relatorio_Chapas_{datetime.now().strftime('%d_%m_%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
        else: st.info("Sem dados")
    else: st.error("Senha incorreta")

elif perfil == "Super Admin":
    st.title("🛠️ Super Admin")
    if st.sidebar.text_input("Senha Mestra", type="password") == "Workaround&97146605":
        sh = conectar_google()
        if st.button("💣 ZERAR TUDO", type="primary"):
            sh.worksheet("Chapas_Producao").clear()
            sh.worksheet("Chapas_Producao").append_row(["id","data_hora","lote","reserva","status_reserva","cod_sap","descricao","qtd","peso_real","largura_real_mm","largura_corte_mm","tamanho_real_mm","tamanho_corte_mm","peso_teorico","sucata"])
            sh.worksheet("Chapas_Lotes").clear()
            sh.worksheet("Chapas_Lotes").append_row(["cod_sap","ultimo_numero"])
            st.success("Limpo!")
            obter_dados_chapas.clear()
        
        st.write("---")
        st.write("Lotes")
        try:
            ws_l = sh.worksheet("Chapas_Lotes")
            df_l = pd.DataFrame(ws_l.get_all_records())
            st.dataframe(df_l)
            c1,c2 = st.columns(2)
            sap = c1.number_input("SAP", step=1)
            nv = c2.number_input("Novo", step=1)
            if st.button("Atualizar"):
                c = ws_l.find(str(sap))
                ws_l.update_cell(c.row, 2, nv)
                st.success("Feito")
        except: st.error("Erro")
        
        st.write("---")
        st.write("Excluir ID")
        idd = st.number_input("ID", step=1)
        if st.button("Excluir"):
            ws_p = sh.worksheet("Chapas_Producao")
            try:
                c = ws_p.find(str(idd))
                ws_p.delete_rows(c.row)
                st.success("Feito")
                obter_dados_chapas.clear()
            except: st.error("Não achado")
    else: st.error("Negado")
