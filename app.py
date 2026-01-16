import streamlit as st
import pandas as pd
import os
import tempfile
from supabase import create_client, Client
from demoparser2 import DemoParser

st.set_page_config(page_title="CS2 Lab", page_icon="🔬", layout="wide")

# --- CONEXÃO (Mantida para não quebrar, mas não usada no Lab) ---
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except: pass

def extrair_dados(parser, evento):
    """Extrai dados de forma segura"""
    try:
        dados = parser.parse_events([evento])
        if isinstance(dados, list) and len(dados) > 0 and isinstance(dados[0], tuple):
            return pd.DataFrame(dados[0][1])
        if isinstance(dados, pd.DataFrame):
            return dados
        return pd.DataFrame(dados)
    except Exception as e:
        return f"Erro ao ler evento: {e}"

st.title("🔬 Laboratório de Demos CS2")
st.write("Use esta ferramenta para descobrir como o `demoparser2` vê sua demo.")

arquivo = st.file_uploader("Suba a demo para investigar", type=["dem"])

if arquivo:
    # Salva temporário
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo.read())
    caminho = tfile.name
    tfile.close()

    parser = DemoParser(caminho)

    # --- ABA 1: DESCOBRIR O VENCEDOR ---
    st.header("1. Investigação de Vitória")
    st.info("O sistema vai tentar ler eventos de fim de jogo para achar o placar.")
    
    # Eventos promissores para achar o vencedor
    eventos_fim = ['cs_win_panel_match', 'round_announce_match_win', 'round_end']
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Eventos de Fim de Jogo")
        for evt in eventos_fim:
            df = extrair_dados(parser, evt)
            if isinstance(df, pd.DataFrame) and not df.empty:
                st.write(f"✅ **{evt}** (Encontrado!)")
                st.dataframe(df.head(5), use_container_width=True)
            else:
                st.write(f"❌ {evt} (Vazio)")

    with col2:
        st.subheader("Análise de Rounds (round_end)")
        df_round = extrair_dados(parser, "round_end")
        if isinstance(df_round, pd.DataFrame) and not df_round.empty:
            if 'winner' in df_round.columns:
                counts = df_round['winner'].value_counts()
                st.write("Quem ganhou cada round (2=TR, 3=CT):")
                st.write(counts)
                
                # Tenta converter
                try:
                    r_t = len(df_round[df_round['winner'].astype(str).isin(['2', '2.0'])])
                    r_ct = len(df_round[df_round['winner'].astype(str).isin(['3', '3.0'])])
                    st.metric("Placar Calculado", f"{r_t} x {r_ct}")
                except:
                    st.error("Erro ao converter coluna 'winner'")
            else:
                st.error("Coluna 'winner' não existe em round_end!")
                st.write("Colunas disponíveis:", df_round.columns.tolist())

    # --- ABA 2: LISTAR TUDO ---
    st.divider()
    st.header("2. Explorador Geral")
    
    if st.button("📂 Listar TODOS os eventos da demo"):
        try:
            # Lista todos os eventos disponíveis na demo
            todos_eventos = parser.list_game_events()
            st.success(f"Encontrados {len(todos_eventos)} tipos de eventos!")
            
            evento_escolhido = st.selectbox("Escolha um evento para ver os dados:", todos_eventos)
            
            if evento_escolhido:
                df_raw = extrair_dados(parser, evento_escolhido)
                st.write(f"Mostrando dados brutos de: **{evento_escolhido}**")
                st.dataframe(df_raw, use_container_width=True)
                
        except Exception as e:
            st.error(f"Erro ao listar eventos: {e}")

    # Limpeza
    os.remove(caminho)