import streamlit as st
import pandas as pd
import io
import os
import sqlite3
import math
from datetime import datetime

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Sistema Chapas", layout="wide")

# CSS BLINDADO
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
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
</style>
""", unsafe_allow_html=True)

# --- 1. BANCO DE DADOS ---
def init_db():
    conn = sqlite3.connect('dados_chapas.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS producao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_hora TEXT,
            lote TEXT,
            reserva TEXT,
            status_reserva TEXT DEFAULT 'Pendente',
            cod_sap INTEGER,
            descricao TEXT,
            qtd INTEGER,
            peso_real REAL,
            largura_real_mm INTEGER,
            largura_corte_mm INTEGER,
            tamanho_real_mm INTEGER,
            tamanho_corte_mm INTEGER,
            peso_teorico REAL,
            sucata REAL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS sequencia_lotes (
            cod_sap INTEGER PRIMARY KEY,
            ultimo_numero INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def obter_e_incrementar_lote(cod_sap, apenas_visualizar=False):
    conn = sqlite3.connect('dados_chapas.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT ultimo_numero FROM sequencia_lotes WHERE cod_sap = ?", (cod_sap,))
    resultado = c.fetchone()
    if resultado:
        ultimo = resultado[0]
        proximo = ultimo + 1
    else:
        ultimo = 0
        proximo = 1
    prefixo = "BRASA"
    lote_formatado = f"{prefixo}{proximo:05d}"
    if not apenas_visualizar:
        c.execute('''
            INSERT INTO sequencia_lotes (cod_sap, ultimo_numero) 
            VALUES (?, ?) 
            ON CONFLICT(cod_sap) DO UPDATE SET ultimo_numero = ?
        ''', (cod_sap, proximo, proximo))
        conn.commit()
    conn.close()
    return lote_formatado

def salvar_no_banco(dados):
    lote_oficial = obter_e_incrementar_lote(dados['Cód. SAP'], apenas_visualizar=False)
    conn = sqlite3.connect('dados_chapas.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''
        INSERT INTO producao (data_hora, lote, reserva, status_reserva, cod_sap, descricao, qtd, peso_real, largura_real_mm, largura_corte_mm, tamanho_real_mm, tamanho_corte_mm, peso_teorico, sucata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        lote_oficial,
        dados['Reserva'],
        "Pendente",
        dados['Cód. SAP'],
        dados['Descrição'],
        dados['Qtd'],
        dados['Peso Balança (kg)'],
        dados['Largura Real (mm)'],
        dados['Largura Corte (mm)'],
        dados['Tamanho Real (mm)'],
        dados['Tamanho Corte (mm)'],
        dados['Peso Teórico'],
        dados['Sucata']
    ))
    conn.commit()
    conn.close()
    return lote_oficial

def ler_banco():
    conn = sqlite3.connect('dados_chapas.db', check_same_thread=False)
    df = pd.read_sql_query("SELECT * FROM producao ORDER BY id DESC", conn)
    conn.close()
    return df

def atualizar_status_lote(df_editado):
    conn = sqlite3.connect('dados_chapas.db', check_same_thread=False)
    c = conn.cursor()
    for index, row in df_editado.iterrows():
        c.execute("UPDATE producao SET status_reserva = ? WHERE id = ?", (row['status_reserva'], row['id']))
    conn.commit()
    conn.close()

def limpar_banco():
    conn = sqlite3.connect('dados_chapas.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("DELETE FROM producao")
    conn.commit()
    conn.close()

init_db()

# --- 2. FUNÇÕES AUXILIARES ---
def formatar_br(valor):
    try:
        if pd.isna(valor) or valor == "": return "0,000"
        val = float(valor)
        return f"{val:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

def regra_multiplos_300_baixo(mm):
    try:
        valor = int(float(mm))
        return (valor // 300) * 300
    except: return 0

@st.cache_data
def carregar_base_sap():
    try:
        if os.path.exists("base_sap.xlsx"):
            df = pd.read_excel("base_sap.xlsx")
        else:
            pasta_script = os.path.dirname(os.path.abspath(__file__))
            caminho_fixo = os.path.join(pasta_script, "base_sap.xlsx")
            if os.path.exists(caminho_fixo):
                df = pd.read_excel(caminho_fixo)
            else:
                return None
        
        df.columns = df.columns.str.strip()
        df['Produto'] = pd.to_numeric(df['Produto'], errors='coerce').fillna(0).astype(int)
        if df['Peso por Metro'].dtype == 'object':
                df['Peso por Metro'] = df['Peso por Metro'].str.replace(',', '.').astype(float)
        return df
    except: 
        return None

# --- 3. CONTROLE DE ACESSO ---
st.sidebar.title("🔐 Acesso Chapas")
modo_acesso = st.sidebar.radio("Selecione o Perfil:", ["Operador (Chão de Fábrica)", "Administrador (Escritório)"])

df_sap = carregar_base_sap()

# ==============================================================================
# TELA 1: OPERADOR
# ==============================================================================
if modo_acesso == "Operador (Chão de Fábrica)":
    st.title("🏭 Chapas: Bipagem")
    
    if df_sap is None:
        st.error("🚨 O arquivo `base_sap.xlsx` não foi encontrado!")
    else:
        if 'wizard_data' not in st.session_state: st.session_state.wizard_data = {}
        if 'wizard_step' not in st.session_state: st.session_state.wizard_step = 0
        if 'item_id' not in st.session_state: st.session_state.item_id = 0 
        if 'proximo_lote_visual' not in st.session_state: st.session_state.proximo_lote_visual = ""

        @st.dialog("📦 Entrada de Chapas")
        def wizard_item():
            st.write(f"**Item:** {st.session_state.wizard_data.get('Cód. SAP')} - {st.session_state.wizard_data.get('Descrição')}")
            st.info(f"🏷️ Próximo Lote: **{st.session_state.proximo_lote_visual}**")
            st.markdown("---")
            
            # PASSO 1
            if st.session_state.wizard_step == 1:
                with st.form("form_reserva"):
                    reserva = st.text_input("1. Nº da Reserva:", key=f"res_{st.session_state.item_id}")
                    st.write("")
                    if st.form_submit_button("PRÓXIMO >>", use_container_width=True, type="primary"):
                        if reserva.strip():
                            st.session_state.wizard_data['Reserva'] = reserva
                            st.session_state.wizard_step = 2
                            st.rerun()
                        else:
                            st.error("⚠️ Digite a Reserva!")

            # PASSO 2
            elif st.session_state.wizard_step == 2:
                with st.form("form_qtd"):
                    qtd = st.number_input("2. Quantidade (Peças):", min_value=1, step=1, value=1, key=f"qtd_{st.session_state.item_id}")
                    st.write("")
                    if st.form_submit_button("PRÓXIMO >>", use_container_width=True, type="primary"):
                        st.session_state.wizard_data['Qtd'] = qtd
                        st.session_state.wizard_step = 3
                        st.rerun()

            # PASSO 3
            elif st.session_state.wizard_step == 3:
                with st.form("form_peso"):
                    peso = st.number_input("3. Peso Real Balança (kg):", min_value=0.000, step=0.001, format="%.3f", key=f"peso_{st.session_state.item_id}")
                    st.write("")
                    if st.form_submit_button("PRÓXIMO >>", use_container_width=True, type="primary"):
                        if peso > 0:
                            st.session_state.wizard_data['Peso Balança (kg)'] = peso
                            st.session_state.wizard_step = 4
                            st.rerun()
                        else:
                            st.error("⚠️ Peso não pode ser Zero!")

            # PASSO 4
            elif st.session_state.wizard_step == 4:
                with st.form("form_largura"):
                    largura = st.number_input("4. Largura Real (mm):", min_value=0, step=1, key=f"larg_{st.session_state.item_id}")
                    larg_multiplo = regra_multiplos_300_baixo(largura)
                    if largura > 0:
                        st.caption(f"Regra 300mm: {largura}mm -> **{larg_multiplo}mm** (Arred. p/ Baixo)")
                    st.write("")
                    if st.form_submit_button("PRÓXIMO >>", use_container_width=True, type="primary"):
                        if largura > 0:
                            st.session_state.wizard_data['Largura Real (mm)'] = largura
                            st.session_state.wizard_step = 5
                            st.rerun()
                        else:
                            st.error("⚠️ Largura não pode ser Zero!")

            # PASSO 5
            elif st.session_state.wizard_step == 5:
                with st.form("form_comp"):
                    comp = st.number_input("5. Comprimento Real (mm):", min_value=0, step=1, key=f"comp_{st.session_state.item_id}")
                    comp_multiplo = regra_multiplos_300_baixo(comp)
                    if comp > 0:
                        st.caption(f"Regra 300mm: {comp}mm -> **{comp_multiplo}mm** (Arred. p/ Baixo)")
                    st.write("")
                    
                    if st.form_submit_button("✅ SALVAR E FINALIZAR", use_container_width=True, type="primary"):
                        if comp > 0:
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
                            st.rerun()
                        else:
                            st.error("⚠️ Comprimento não pode ser Zero!")

        def iniciar_bipagem():
            codigo = st.session_state.input_scanner
            if codigo:
                try:
                    cod_limpo = str(codigo).strip().split(":")[-1]
                    cod_int = int(cod_limpo)
                    produto = df_sap[df_sap['Produto'] == cod_int]
                    if not produto.empty:
                        st.session_state.item_id += 1 
                        prev = obter_e_incrementar_lote(cod_int, apenas_visualizar=True)
                        st.session_state.proximo_lote_visual = prev
                        
                        st.session_state.wizard_data = {
                            "Cód. SAP": cod_int,
                            "Descrição": produto.iloc[0]['Descrição do produto'],
                            "Fator SAP": produto.iloc[0]['Peso por Metro']
                        }
                        st.session_state.wizard_step = 1
                    else:
                        st.toast("Material não encontrado!", icon="🚫")
                        st.session_state.input_scanner = ""
                except:
                    st.session_state.input_scanner = ""

        if st.session_state.wizard_step > 0:
            wizard_item()

        st.text_input("BIPAR CÓDIGO CHAPA:", key="input_scanner", on_change=iniciar_bipagem)
        st.info("ℹ️ Sistema Chapas: Regra 300mm (Para Baixo).")

# ==============================================================================
# TELA 2: ADMINISTRADOR
# ==============================================================================
elif modo_acesso == "Administrador (Escritório)":
    st.title("💻 Admin: Controle de Chapas")
    
    SENHA_CORRETA = "Br@met4lChapas"

    senha_digitada = st.sidebar.text_input("Senha Admin", type="password")
    
    if df_sap is None:
        st.sidebar.warning("⚠️ Base SAP desconectada.")

    if senha_digitada == SENHA_CORRETA:
        st.sidebar.success("Acesso Chapas Liberado")
        
        if st.button("🔄 Atualizar Tabela"):
            st.rerun()
            
        df_banco = ler_banco()
        
        if not df_banco.empty:
            c1, c2, c3 = st.columns(3)
            c1.metric("Itens", len(df_banco))
            c2.metric("Peso Total", formatar_br(df_banco['peso_real'].sum()) + " kg")
            c3.metric("Sucata Total", formatar_br(df_banco['sucata'].sum()) + " kg")
            
            st.markdown("### Conferência")
            
            df_editado = st.data_editor(
                df_banco,
                use_container_width=True,
                column_config={
                    "id": None, 
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
            
            if st.button("💾 Salvar Alterações de Status"):
                atualizar_status_lote(df_editado)
                st.success("Status atualizados!")
                st.rerun()
            
            # --- LÓGICA DE EXPORTAÇÃO CORRIGIDA ---
            lista_exportacao = []

            for index, row in df_banco.iterrows():
                # A) Linha ORIGINAL
                linha_original = {
                    'Lote': row['lote'],
                    'Reserva': row['reserva'],
                    'SAP': row['cod_sap'],
                    'Descrição': row['descricao'],
                    'Peso Lançamento (kg)': formatar_br(row['peso_teorico']), # Peso Teórico
                    'Status': row['status_reserva'],
                    'Qtd': row['qtd'],
                    'Largura Real': row['largura_real_mm'],
                    'Largura Consid.': row['largura_corte_mm'],
                    'Comp. Real': row['tamanho_real_mm'],
                    'Comp. Consid.': row['tamanho_corte_mm']
                }
                lista_exportacao.append(linha_original)

                # B) Linha VIRTUAL (SUCATA)
                # Verifica se existe sucata (maior que 0.001 para evitar sujeira de ponto flutuante)
                if row['sucata'] > 0.001:
                    linha_virtual = {
                        'Lote': "VIRTUAL",
                        'Reserva': row['reserva'],
                        'SAP': row['cod_sap'],
                        'Descrição': f"SUCATA - {row['descricao']}",
                        'Peso Lançamento (kg)': formatar_br(row['sucata']), # Peso Sucata
                        'Status': row['status_reserva'],
                        'Qtd': 1,
                        'Largura Real': 0,
                        'Largura Consid.': 0,
                        'Comp. Real': 0,
                        'Comp. Consid.': 0
                    }
                    lista_exportacao.append(linha_virtual)

            df_export_final = pd.DataFrame(lista_exportacao)
            
            cols_order = ['Lote', 'Reserva', 'SAP', 'Descrição', 'Peso Lançamento (kg)', 'Status', 'Qtd', 'Largura Real', 'Largura Consid.', 'Comp. Real', 'Comp. Consid.']
            # Garante que só ordena colunas que existem
            cols_final = [c for c in cols_order if c in df_export_final.columns]
            df_export_final = df_export_final[cols_final]
                
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_export_final.to_excel(writer, index=False)
            
            st.markdown("---")
            st.download_button("📥 Baixar Excel Chapas", buffer.getvalue(), "Relatorio_Chapas.xlsx", type="primary")
            
            if st.button("🗑️ Limpar Banco Chapas", type="secondary"):
                limpar_banco()
                st.rerun()
        else:
            st.info("Nenhum dado de chapa.")
    elif senha_digitada:
        st.sidebar.error("Senha Incorreta")
