import streamlit as st
import pandas as pd
import os
import tempfile
from demoparser2 import DemoParser

st.set_page_config(page_title="CS2 Raio-X", page_icon="🩻", layout="wide")

# Lista simplificada para focar no erro
AMIGOS_DEBUG = {
    "Ph (Ph1L)": "76561198301569089",
    "Pablo (Cyrax)": "76561198143002755"
}

def ler_evento(parser, evento):
    try:
        dados = parser.parse_events([evento])
        if isinstance(dados, list) and len(dados) > 0:
            return pd.DataFrame(dados[0][1])
        return pd.DataFrame(dados)
    except: return pd.DataFrame()

st.title("🩻 Raio-X da Demo")
st.write("Vamos ver exatamente o que a demo está 'pensando'.")

arquivo = st.file_uploader("Suba a demo problemática", type=["dem"])

if arquivo:
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo.read())
    caminho = tfile.name
    tfile.close()

    parser = DemoParser(caminho)

    # --- 1. VERIFICAR SE EXISTEM EVENTOS DE TIME ---
    st.header("1. Investigação de Troca de Time")
    st.info("Procurando eventos 'player_team' (troca de time) e 'player_spawn' (nascimento)...")
    
    df_team = ler_evento(parser, "player_team")
    df_spawn = ler_evento(parser, "player_spawn")
    
    if df_team.empty:
        st.error("❌ CRÍTICO: O evento 'player_team' está VAZIO nesta demo.")
    else:
        st.success(f"✅ Encontrados {len(df_team)} registros de troca de time.")
        st.write("Amostra bruta (primeiras 5 linhas):")
        st.dataframe(df_team.head())

    # --- 2. RASTREAR O JOGADOR 'PH' ---
    st.header("2. Rastreando o Ph (76561198301569089)")
    
    # Filtra eventos só do Ph
    id_alvo = "76561198301569089"
    
    st.subheader("Eventos de Nascimento (Spawn)")
    if not df_spawn.empty:
        # Tenta achar a coluna certa do ID
        col_id = next((c for c in df_spawn.columns if c in ['user_steamid', 'steamid', 'userid_steamid']), None)
        if col_id:
            spawns_ph = df_spawn[df_spawn[col_id].astype(str).str.contains(id_alvo)]
            if not spawns_ph.empty:
                st.dataframe(spawns_ph[['tick', 'team_num', 'user_team_num'] if 'user_team_num' in spawns_ph.columns else ['tick', 'team_num']])
            else:
                st.warning("⚠️ O ID do Ph não foi encontrado nos Spawns!")
        else:
            st.error("Não achei coluna de ID no Spawn.")
    
    st.subheader("Eventos de Troca de Time (Player Team)")
    if not df_team.empty:
        col_id = next((c for c in df_team.columns if c in ['user_steamid', 'steamid', 'userid_steamid']), None)
        if col_id:
            trocas_ph = df_team[df_team[col_id].astype(str).str.contains(id_alvo)]
            if not trocas_ph.empty:
                st.dataframe(trocas_ph[['tick', 'team', 'oldteam', 'disconnect']])
            else:
                st.warning("⚠️ O ID do Ph não foi encontrado nas Trocas de Time!")

    # --- 3. INVESTIGAR ROUNDS ---
    st.header("3. Cronologia dos Rounds")
    df_round = ler_evento(parser, "round_end")
    
    if not df_round.empty and 'winner' in df_round.columns:
        st.dataframe(df_round[['tick', 'winner', 'reason']])
    else:
        st.error("❌ Evento 'round_end' vazio ou sem vencedor.")

    os.remove(caminho)