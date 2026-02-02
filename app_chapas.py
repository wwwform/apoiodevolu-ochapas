import streamlit as st
import pandas as pd
from google.cloud import firestore
from google.oauth2 import service_account
from datetime import datetime
import json
import io
import os

st.set_page_config(page_title="Sistema Chapas", layout="wide")
st.markdown("""<style>header{display:none;} .stDeployButton{display:none;} button{height:3.5rem;}</style>""", unsafe_allow_html=True)

@st.cache_resource
def get_db():
    key_dict = json.loads(json.dumps(st.secrets["firebase"]))
    creds = service_account.Credentials.from_service_account_info(key_dict)
    return firestore.Client(credentials=creds, project=key_dict["project_id"])

def get_proximo_lote(db, cod_sap):
    doc_ref = db.collection('controles').document('lotes_chapas')
    doc = doc_ref.get()
    dados = doc.to_dict() if doc.exists else {}
    sap_str = str(cod_sap)
    novo = dados.get(sap_str, 0) + 1
    doc_ref.set({sap_str: novo}, merge=True)
    return f"BRASA{novo:05d}"

def salvar(dados):
    db = get_db()
    lote = get_proximo_lote(db, dados['cod_sap'])
    payload = dados.copy()
    payload['lote'] = lote
    payload['data_hora'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    payload['timestamp'] = datetime.now()
    payload['status_reserva'] = "Pendente"
    db.collection('chapas_producao').add(payload)
    return lote

def formatar_br(v):
    try: return f"{float(v):,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,000"

def regra_300(mm):
    try: return (int(float(mm)) // 300) * 300
    except: return 0

@st.cache_data
def carregar_base_sap():
    path = "base_sap.xlsx"
    if not os.path.exists(path): return None
    try:
        df = pd.read_excel(path, dtype=str)
        df.columns = df.columns.str.strip().str.upper()
        col_prod = next((c for c in df.columns if 'PRODUTO' in c), None)
        col_peso = next((c for c in df.columns if 'PESO' in c and 'METRO' in c), None)
        if col_prod and col_peso:
            df['PRODUTO'] = pd.to_numeric(df[col_prod], errors='coerce').fillna(0).astype(int)
            def cv(x):
                if pd.isna(x): return 0.0
                s = str(x).strip().replace('.','').replace(',','.')
                try: return float(s)
                except: return 0.0
            df['PESO_FATOR'] = df[col_peso].apply(cv)
            return df
        return None
    except: return None

df_sap = carregar_base_sap()
st.sidebar.title("🔐 Acesso Chapas")
perfil = st.sidebar.radio("Perfil:", ["Operador", "Administrador", "Super Admin"])

if perfil == "Operador":
    st.title("🏭 Operador")
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
                            st.session_state.wizard_data.update({'reserva':res, 'PESO_FATOR':fator_real})
                            st.session_state.wizard_step = 2
                            st.rerun()
                        else: st.error("Obrigatório")
            elif st.session_state.wizard_step == 2:
                with st.form("f2"):
                    qtd = st.number_input("2. Qtd:", min_value=1, step=1)
                    if st.form_submit_button("PRÓXIMO"):
                        st.session_state.wizard_data['qtd'] = qtd
                        st.session_state.wizard_step = 3
                        st.rerun()
            elif st.session_state.wizard_step == 3:
                with st.form("f3"):
                    peso = st.number_input("3. Peso Real (kg):", min_value=0.001, format="%.3f")
                    if st.form_submit_button("PRÓXIMO"):
                        st.session_state.wizard_data['peso_real'] = peso
                        st.session_state.wizard_step = 4
                        st.rerun()
            elif st.session_state.wizard_step == 4:
                with st.form("f4"):
                    larg = st.number_input("4. Largura (mm):", min_value=0)
                    if st.form_submit_button("PRÓXIMO"):
                        st.session_state.wizard_data['largura'] = larg
                        st.session_state.wizard_step = 5
                        st.rerun()
            elif st.session_state.wizard_step == 5:
                comp = st.number_input("5. Comp. Real (mm):", min_value=0)
                fator = st.session_state.wizard_data['PESO_FATOR']
                q = st.session_state.wizard_data['qtd']
                larg_real = st.session_state.wizard_data['largura']
                lc = regra_300(larg_real)
                tc = regra_300(comp)
                pt = fator * (lc/1000.0) * (tc/1000.0) * q
                
                if comp > 0: st.info(f"Calc: **{formatar_br(pt)} kg**")
                
                if st.button("✅ SALVAR"):
                    if comp > 0:
                        dados = {
                            'cod_sap': int(st.session_state.wizard_data['Cód. SAP']),
                            'descricao': st.session_state.wizard_data['Descrição'],
                            'reserva': st.session_state.wizard_data['reserva'],
                            'qtd': int(q),
                            'peso_real': float(st.session_state.wizard_data['peso_real']),
                            'largura_real_mm': int(larg_real),
                            'largura_corte_mm': int(lc),
                            'tamanho_real_mm': int(comp),
                            'tamanho_corte_mm': int(tc),
                            'peso_teorico': float(pt),
                            'sucata': float(st.session_state.wizard_data['peso_real'] - pt)
                        }
                        lote = salvar(dados)
                        st.toast(f"Salvo: {lote}")
                        st.session_state.wizard_step = 0
                        st.session_state.input_scanner = ""
                        time.sleep(1)
                        st.rerun()
                    else: st.error("Inválido")

        def check():
            c = st.session_state.input_scanner
            if c:
                try:
                    cod = int(str(c).strip().split(":")[-1])
                    row = df_sap[df_sap['PRODUTO'] == cod]
                    if not row.empty:
                        st.session_state.wizard_data = {
                            "Cód. SAP": cod,
                            "Descrição": row.iloc[0]['DESCRIÇÃO DO PRODUTO'],
                            "PESO_FATOR": row.iloc[0]['PESO_FATOR']
                        }
                        st.session_state.wizard_step = 1
                    else: st.toast("Não encontrado")
                except: pass
                st.session_state.input_scanner = ""

        if st.session_state.wizard_step > 0: wizard()
        st.text_input("BIPAR:", key="input_scanner", on_change=check)

elif perfil == "Administrador":
    st.title("💻 Admin")
    if st.sidebar.text_input("Senha", type="password") == "Br@met4lChapas":
        if st.button("Atualizar"): st.rerun()
        db = get_db()
        docs = db.collection('chapas_producao').order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
        lista = [d.to_dict() | {'id_doc': d.id} for d in docs]
        df = pd.DataFrame(lista)
        
        if not df.empty:
            c1,c2,c3 = st.columns(3)
            c1.metric("Itens", len(df))
            c2.metric("Total", formatar_br(df['peso_real'].sum()))
            c3.metric("Sucata", formatar_br(df['sucata'].sum()))
            
            df_show = st.data_editor(df, key="ed", use_container_width=True, column_config={
                "id_doc": st.column_config.TextColumn(disabled=True),
                "timestamp": None,
                "status_reserva": st.column_config.SelectboxColumn("Status", options=["Pendente", "Ok - Lançada"])
            })
            
            if st.button("Salvar"):
                for i, row in df_show.iterrows():
                    orig = df[df['id_doc'] == row['id_doc']].iloc[0]['status_reserva']
                    if row['status_reserva'] != orig:
                        db.collection('chapas_producao').document(row['id_doc']).update({'status_reserva': row['status_reserva']})
                st.success("Salvo!")
                st.rerun()
                
            b = io.BytesIO()
            with pd.ExcelWriter(b, engine='openpyxl') as w:
                df_export = df_show.drop(columns=['id_doc', 'timestamp'], errors='ignore')
                df_export.to_excel(w, index=False, sheet_name='Relatorio')
                ws = w.sheets['Relatorio']
                try:
                    cols_idx = [i+1 for i, c in enumerate(df_export.columns) if 'peso' in c.lower() or 'sucata' in c.lower()]
                    for r in range(2, ws.max_row + 1):
                        for c in cols_idx: ws.cell(row=r, column=c).number_format = '#,##0.000'
                except: pass
            st.download_button("Baixar Excel", b.getvalue(), "Relatorio.xlsx", "primary")
        else: st.info("Vazio")
    else: st.error("Senha incorreta")

elif perfil == "Super Admin":
    st.title("🛠️ Super Admin")
    if st.sidebar.text_input("Senha", type="password") == "Workaround&97146605":
        db = get_db()
        if st.button("💣 APAGAR TUDO", type="primary"):
            for d in db.collection('chapas_producao').stream(): d.reference.delete()
            db.collection('controles').document('lotes_chapas').delete()
            st.success("Limpo")
        
        st.write("---")
        doc = db.collection('controles').document('lotes_chapas').get()
        if doc.exists:
            sap = st.number_input("SAP", step=1)
            val = st.number_input("Valor", step=1)
            if st.button("Atualizar"):
                db.collection('controles').document('lotes_chapas').update({str(sap): val})
                st.success("Feito")
