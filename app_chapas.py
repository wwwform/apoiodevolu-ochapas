import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import os
import io # <--- IMPORTANTE

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
    except Exception as e:
        return None

def garantir_cabecalhos():
    sh = conectar_google()
    if sh is None:
        st.error("Erro fatal: Falha na conexão com Google Sheets.")
        return
    try:
        try: ws_prod = sh.worksheet("Chapas_Producao")
        except: ws_prod = sh.add_worksheet(title="Chapas_Producao", rows=1000, cols=20)
        if not ws_prod.row_values(1):
            ws_prod.append_row(["id", "data_hora", "lote", "reserva", "status_reserva", "cod_sap", "descricao", "qtd", "peso_real", "largura_real_mm", "largura_corte_mm", "tamanho_real_mm", "tamanho_corte_mm", "peso_teorico", "sucata"])
        
        try: ws_lotes = sh.worksheet("Chapas_Lotes")
        except: ws_lotes = sh.add_worksheet(title="Chapas_Lotes", rows=1000, cols=5)
        if not ws_lotes.row_values(1):
            ws_lotes.append_row(["cod_sap", "ultimo_numero"])
    except Exception as e: st.error(f"Erro ao configurar abas: {e}")

garantir_cabecalhos()

# --- RASTREADOR DE ARQUIVO (SÓ PARA CHAPAS) ---
@st.cache_data
def carregar_base_sap():
    # 1. Caminho Direto
    if os.path.exists("base_sap.xlsx"): return ler_excel("base_sap.xlsx")
    
    # 2. Caminho Absoluto
    pasta_script = os.path.dirname(os.path.abspath(__file__))
    caminho_fixo = os.path.join(pasta_script, "base_sap.xlsx")
    if os.path.exists(caminho_fixo): return ler_excel(caminho_fixo)
    
    # 3. Varredura
    for arquivo in os.listdir(pasta_script):
        if arquivo.lower() == "base_sap.xlsx":
            return ler_excel(os.path.join(pasta_script, arquivo))
    
    return None

def ler_excel(caminho):
    try:
        df = pd.read_excel(caminho)
        df.columns = df.columns.str.strip()
        df['Produto'] = pd.to_numeric(df['Produto'], errors='coerce').fillna(0).astype(int)
        if df['Peso por Metro'].dtype == 'object':
                df['Peso por Metro'] = df['Peso por Metro'].str.replace(',', '.').astype(float)
        return df
    except: return None

# --- FUNÇÕES ---
def ler_banco():
    sh = conectar_google()
    ws = sh.worksheet("Chapas_Producao")
    dados = ws.get_all_records()
    df = pd.DataFrame(dados)
    cols_num = ['id', 'cod_sap', 'qtd', 'peso_real', 'largura_real_mm', 'largura_corte_mm', 'tamanho_real_mm', 'tamanho_corte_mm', 'peso_teorico', 'sucata']
    for c in cols_num:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
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
    lote_oficial = obter_e_incrementar_lote(dados['Cód. SAP'])
    novo_id = int(datetime.now().timestamp() * 1000)
    
    linha = [
        novo_id, datetime.now().strftime("%d/%m/%Y %H:%M:%S"), lote_oficial,
        dados['Reserva'], "Pendente", int(dados['Cód. SAP']), dados['Descrição'],
        int(dados['Qtd']), float(dados['Peso Balança (kg)']), int(dados['Largura Real (mm)']),
        int(dados['Largura Corte (mm)']), int(dados['Tamanho Real (mm)']),
        int(dados['Tamanho Corte (mm)']), float(dados['Peso Teórico']), float(dados['Sucata'])
    ]
    ws.append_row(linha)
    return lote_oficial

def atualizar_status_lote(df_editado):
    sh = conectar_google()
    ws = sh.worksheet("Chapas_Producao")
    registros_sheet = ws.get_all_records()
    for i, row_sheet in enumerate(registros_sheet):
        id_sheet = row_sheet['id']
        row_editada = df_editado[df_editado['id'] == id_sheet]
        if not row_editada.empty:
            novo_status = row_editada.iloc[0]['status_reserva']
            if row_sheet['status_reserva'] != novo_status:
                ws.update_cell(i + 2, 5, novo_status)

def limpar_banco_completo():
    sh = conectar_google()
    ws_p = sh.worksheet("Chapas_Producao")
    ws_p.clear()
    ws_p.append_row(["id", "data_hora", "lote", "reserva", "status_reserva", "cod_sap", "descricao", "qtd", "peso_real", "largura_real_mm", "largura_corte_mm", "tamanho_real_mm", "tamanho_corte_mm", "peso_teorico", "sucata"])
    ws_l = sh.worksheet("Chapas_Lotes")
    ws_l.clear()
    ws_l.append_row(["cod_sap", "ultimo_numero"])

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

def formatar_br(valor):
    try:
        if pd.isna(valor) or valor == "": return "0,000"
        val = float(valor)
        return f"{val:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

def regra_multiplos_300_baixo(mm):
    try: return (int(float(mm)) // 300) * 300
    except: return 0

# --- CONTROLE DE ACESSO ---
st.sidebar.title("🔐 Acesso Chapas")
modo_acesso = st.sidebar.radio("Selecione o Perfil:", ["Operador (Chão de Fábrica)", "Administrador (Escritório)", "Super Admin"])

df_sap = carregar_base_sap()
if df_sap is None: st.error("ERRO: `base_sap.xlsx` não encontrado.")

# ================= TELA 1: OPERADOR =================
if modo_acesso == "Operador (Chão de Fábrica)":
    st.title("🏭 Chapas: Bipagem")
    if df_sap is not None:
        if 'wizard_data' not in st.session_state: st.session_state.wizard_data = {}
        if 'wizard_step' not in st.session_state: st.session_state.wizard_step = 0
        if 'item_id' not in st.session_state: st.session_state.item_id = 0 

        @st.dialog("📦 Entrada de Chapas")
        def wizard_item():
            st.write(f"**Item:** {st.session_state.wizard_data.get('Cód. SAP')} - {st.session_state.wizard_data.get('Descrição')}")
            st.markdown("---")
            if st.session_state.wizard_step == 1:
                with st.form("form_reserva"):
                    reserva = st.text_input("1. Nº da Reserva:", key=f"res_{st.session_state.item_id}")
                    st.write("")
                    if st.form_submit_button("PRÓXIMO >>", use_container_width=True, type="primary"):
                        if reserva.strip():
                            st.session_state.wizard_data['Reserva'] = reserva
                            st.session_state.wizard_step = 2
                            st.rerun()
                        else: st.error("⚠️ Digite a Reserva!")
            elif st.session_state.wizard_step == 2:
                with st.form("form_qtd"):
                    qtd = st.number_input("2. Quantidade (Peças):", min_value=1, step=1, value=1, key=f"qtd_{st.session_state.item_id}")
                    st.write("")
                    if st.form_submit_button("PRÓXIMO >>", use_container_width=True, type="primary"):
                        st.session_state.wizard_data['Qtd'] = qtd
                        st.session_state.wizard_step = 3
                        st.rerun()
            elif st.session_state.wizard_step == 3:
                with st.form("form_peso"):
                    peso = st.number_input("3. Peso Real Balança (kg):", min_value=0.000, step=0.001, format="%.3f", key=f"peso_{st.session_state.item_id}")
                    st.write("")
                    if st.form_submit_button("PRÓXIMO >>", use_container_width=True, type="primary"):
                        if peso > 0:
                            st.session_state.wizard_data['Peso Balança (kg)'] = peso
                            st.session_state.wizard_step = 4
                            st.rerun()
                        else: st.error("⚠️ Peso não pode ser Zero!")
            elif st.session_state.wizard_step == 4:
                with st.form("form_largura"):
                    largura = st.number_input("4. Largura Real (mm):", min_value=0, step=1, key=f"larg_{st.session_state.item_id}")
                    larg_multiplo = regra_multiplos_300_baixo(largura)
                    if largura > 0: st.caption(f"Regra 300mm: {largura} -> {larg_multiplo}")
                    st.write("")
                    if st.form_submit_button("PRÓXIMO >>", use_container_width=True, type="primary"):
                        if largura > 0:
                            st.session_state.wizard_data['Largura Real (mm)'] = largura
                            st.session_state.wizard_step = 5
                            st.rerun()
                        else: st.error("⚠️ Largura não pode ser Zero!")
            elif st.session_state.wizard_step == 5:
                with st.form("form_comp"):
                    comp = st.number_input("5. Comprimento Real (mm):", min_value=0, step=1, key=f"comp_{st.session_state.item_id}")
                    comp_multiplo = regra_multiplos_300_baixo(comp)
                    if comp > 0: st.caption(f"Regra 300mm: {comp} -> {comp_multiplo}")
                    st.write("")
                    if st.form_submit_button("✅ SALVAR E FINALIZAR", use_container_width=True, type="primary"):
                        if comp > 0:
                            with st.spinner("Salvando na nuvem..."):
                                fator_sap = st.session_state.wizard_data['Fator SAP']
                                qtd_f = st.session_state.wizard_data['Qtd']
                                peso_balanca_f = st.session_state.wizard_data['Peso Balança (kg)']
                                largura_real = st.session_state.wizard_data['Largura Real (mm)']
                                tamanho_real = comp
                                largura_corte = regra_multiplos_300_baixo(largura_real)
                                tamanho_corte = regra_multiplos_300_baixo(tamanho_real)
                                larg_metros = largura_corte / 1000.0
                                comp_metros = tamanho_corte / 1000.0
                                peso_teorico = fator_sap * larg_metros * comp_metros * qtd_f
                                sucata = peso_balanca_f - peso_teorico
                                item_temp = {
                                    "Reserva": st.session_state.wizard_data['Reserva'],
                                    "Cód. SAP": st.session_state.wizard_data['Cód. SAP'],
                                    "Descrição": st.session_state.wizard_data['Descrição'],
                                    "Qtd": qtd_f,
                                    "Peso Balança (kg)": peso_balanca_f,
                                    "Largura Real (mm)": largura_real,
                                    "Largura Corte (mm)": largura_corte,
                                    "Tamanho Real (mm)": tamanho_real,
                                    "Tamanho Corte (mm)": tamanho_corte,
                                    "Peso Teórico": peso_teorico,
                                    "Sucata": sucata
                                }
                                lote_gerado = salvar_no_banco(item_temp)
                                st.toast(f"Chapa Salva! Lote: {lote_gerado}", icon="🏗️")
                                st.session_state.wizard_data = {}
                                st.session_state.wizard_step = 0
                                st.session_state.input_scanner = ""
                                time.sleep(1)
                                st.rerun()
                        else: st.error("⚠️ Comprimento não pode ser Zero!")

        def iniciar_bipagem():
            codigo = st.session_state.input_scanner
            if codigo:
                try:
                    cod_limpo = str(codigo).strip().split(":")[-1]
                    cod_int = int(cod_limpo)
                    produto = df_sap[df_sap['Produto'] == cod_int]
                    if not produto.empty:
                        st.session_state.item_id += 1 
                        st.session_state.wizard_data = {
                            "Cód. SAP": cod_int,
                            "Descrição": produto.iloc[0]['Descrição do produto'],
                            "Fator SAP": produto.iloc[0]['Peso por Metro']
                        }
                        st.session_state.wizard_step = 1
                    else:
                        st.toast("Material não encontrado!", icon="🚫")
                        st.session_state.input_scanner = ""
                except: st.session_state.input_scanner = ""

        if st.session_state.wizard_step > 0: wizard_item()
        st.text_input("BIPAR CÓDIGO CHAPA:", key="input_scanner", on_change=iniciar_bipagem)

# ================= TELA 2: ADMIN =================
elif modo_acesso == "Administrador (Escritório)":
    st.title("💻 Admin: Controle de Chapas (Google Cloud)")
    SENHA_CORRETA = "Br@met4lChapas"
    senha_digitada = st.sidebar.text_input("Senha Admin", type="password")
    
    if senha_digitada == SENHA_CORRETA:
        st.sidebar.success("Acesso Chapas Liberado")
        try: df_banco = ler_banco()
        except:
            st.error("Erro no Google Sheets.")
            df_banco = pd.DataFrame()
        
        if not df_banco.empty:
            tab1, tab2 = st.tabs(["📋 Tabela", "📊 KPIs"])
            with tab1:
                if st.button("🔄 Atualizar"): st.rerun()
                c1, c2, c3 = st.columns(3)
                c1.metric("Itens", len(df_banco))
                c2.metric("Peso Total", formatar_br(df_banco['peso_real'].sum()) + " kg")
                c3.metric("Sucata Total", formatar_br(df_banco['sucata'].sum()) + " kg")
                st.markdown("### Conferência")
                df_editado = st.data_editor(
                    df_banco,
                    use_container_width=True,
                    column_config={
                        "id": st.column_config.NumberColumn("ID", disabled=True),
                        "data_hora": st.column_config.TextColumn("Data", disabled=True),
                        "lote": st.column_config.TextColumn("Lote", disabled=True),
                        "reserva": st.column_config.TextColumn("Reserva", disabled=True),
                        "status_reserva": st.column_config.SelectboxColumn("Status", width="medium", options=["Pendente", "Ok - Lançada"], required=True),
                        "cod_sap": st.column_config.NumberColumn("SAP", format="%d", disabled=True),
                        "descricao": st.column_config.TextColumn("Descrição", disabled=True),
                        "qtd": st.column_config.NumberColumn("Qtd", disabled=True),
                        "largura_corte_mm": st.column_config.NumberColumn("Largura (Consid.)", format="%d", disabled=True),
                        "peso_real": st.column_config.NumberColumn("Peso Real", format="%.3f", disabled=True),
                        "tamanho_corte_mm": st.column_config.NumberColumn("Comp. (Consid.)", format="%d", disabled=True),
                        "sucata": st.column_config.NumberColumn("Sucata", format="%.3f", disabled=True),
                        "peso_teorico": None
                    },
                    key="editor_admin"
                )
                if st.button("💾 Salvar Status"):
                    with st.spinner("Atualizando..."): atualizar_status_lote(df_editado)
                    st.success("Salvo!")
                    st.rerun()
                
                lista_exportacao = []
                for index, row in df_banco.iterrows():
                    linha_original = {
                        'Lote': row['lote'], 'Reserva': row['reserva'], 'SAP': row['cod_sap'],
                        'Descrição': row['descricao'], 'Peso Lançamento (kg)': formatar_br(row['peso_teorico']), 
                        'Status': row['status_reserva'], 'Qtd': row['qtd'],
                        'Largura Real': row['largura_real_mm'], 'Largura Consid.': row['largura_corte_mm'],
                        'Comp. Real': row['tamanho_real_mm'], 'Comp. Consid.': row['tamanho_corte_mm']
                    }
                    lista_exportacao.append(linha_original)
                    if row['sucata'] > 0.001:
                        linha_virtual = {
                            'Lote': "VIRTUAL", 'Reserva': row['reserva'], 'SAP': row['cod_sap'],
                            'Descrição': f"SUCATA - {row['descricao']}", 'Peso Lançamento (kg)': formatar_br(row['sucata']), 
                            'Status': row['status_reserva'], 'Qtd': 1,
                            'Largura Real': 0, 'Largura Consid.': 0,
                            'Comp. Real': 0, 'Comp. Consid.': 0
                        }
                        lista_exportacao.append(linha_virtual)

                df_export_final = pd.DataFrame(lista_exportacao)
                if not df_export_final.empty:
                    cols_final = [c for c in ['Lote', 'Reserva', 'SAP', 'Descrição', 'Peso Lançamento (kg)', 'Status', 'Qtd', 'Largura Real', 'Largura Consid.', 'Comp. Real', 'Comp. Consid.'] if c in df_export_final.columns]
                    df_export_final = df_export_final[cols_final]
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        df_export_final.to_excel(writer, index=False)
                    st.markdown("---")
                    st.download_button("📥 Baixar Excel Chapas", buffer.getvalue(), "Relatorio_Chapas.xlsx", type="primary")
            
            with tab2:
                st.subheader("KPIs")
                peso_total = df_banco['peso_real'].sum()
                sucata_total = df_banco['sucata'].sum()
                if peso_total > 0: pct_sucata = (sucata_total / peso_total) * 100
                else: pct_sucata = 0
                c1, c2, c3 = st.columns(3)
                c1.metric("Produção", f"{peso_total:,.2f} kg")
                c2.metric("Sucata", f"{sucata_total:,.2f} kg")
                c3.metric("Índice Sucata", f"{pct_sucata:.2f}%")
                st.write("### Top Materiais")
                st.bar_chart(df_banco.groupby("descricao")[["peso_real"]].sum().sort_values("peso_real", ascending=False).head(10))
        else: st.info("Sem dados.")
    elif senha_digitada: st.sidebar.error("Senha Incorreta")

# ================= TELA 3: SUPER ADMIN =================
elif modo_acesso == "Super Admin":
    st.title("🛠️ Super Admin (Google Cloud)")
    SENHA_MESTRA = "Workaround&97146605"
    senha_digitada = st.sidebar.text_input("Senha Mestra", type="password")
    
    if senha_digitada == SENHA_MESTRA:
        st.sidebar.success("Acesso ROOT Liberado")
        
        st.subheader("1. Reset Geral (Perigo)")
        st.warning("⚠️ Apaga TODAS as linhas de 'Chapas_Producao' e 'Chapas_Lotes'.")
        if st.button("💣 ZERAR PLANILHA COMPLETA", type="primary"):
            with st.spinner("Limpando Google Sheets..."):
                limpar_banco_completo()
            st.success("Planilhas limpas com sucesso!")
        
        st.markdown("---")
        st.subheader("2. Ajustar Contador de Lotes")
        
        sh = conectar_google()
        ws_lotes = sh.worksheet("Chapas_Lotes")
        dados_lotes = ws_lotes.get_all_records()
        df_lotes = pd.DataFrame(dados_lotes)
        st.dataframe(df_lotes)
        
        c1, c2, c3 = st.columns(3)
        cod_sap_alvo = c1.number_input("Cód. SAP:", step=1, format="%d")
        novo_valor = c2.number_input("Novo Valor:", min_value=0, step=1)
        if c3.button("Atualizar Lote"):
            ajustar_contador_lote(cod_sap_alvo, novo_valor)
            st.success("Atualizado!")
            st.rerun()
            
        st.markdown("---")
        st.subheader("3. Excluir Linha por ID")
        
        df_prod = ler_banco()
        st.dataframe(df_prod)
        
        c_del1, c_del2 = st.columns([1,2])
        id_del = c_del1.number_input("ID para excluir:", step=1, format="%d")
        if c_del2.button("🗑️ Excluir"):
            if id_del > 0:
                with st.spinner("Deletando da nuvem..."):
                    sucesso = excluir_linha_por_id(id_del)
                if sucesso: 
                    st.success("Excluído!")
                    st.rerun()
                else: st.error("ID não encontrado.")
    
    elif senha_digitada: st.error("Acesso Negado")
