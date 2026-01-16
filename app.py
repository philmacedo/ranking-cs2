import streamlit as st
import pandas as pd
import os
import tempfile
from supabase import create_client, Client
from demoparser2 import DemoParser

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="CS2 Pro Ranking", page_icon="🕵️", layout="wide")

try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
except FileNotFoundError:
    st.error("❌ Erro: Secrets não encontrados.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- LISTA DE AMIGOS ---
AMIGOS = {
    "Ph (Ph1L)": "76561198301569089", 
    "Pablo (Cyrax)": "76561198143002755",
    "Bruno (Safadinha)": "76561198187604726",
    "Daniel (Ocharadas)": "76561199062357951",
    "LEO (Trewan)": "76561198160033077",
    "FERNANDO (Nandin)": "76561198185508959",
    "DG (dgtremsz)":"76561199402154960",
    "Arlon (M4CH)": "76561197978110112",
}

# --- 2. FUNÇÕES ---
def atualizar_banco(stats_novos):
    progresso = st.progress(0)
    total = len(stats_novos)
    contador = 0

    for nick, dados in stats_novos.items():
        if dados['Matches'] > 0:
            response = supabase.table('player_stats').select("*").eq('nickname', nick).execute()
            
            novos_dados = {
                "kills": dados['Kills'],
                "deaths": dados['Deaths'],
                "matches": dados['Matches'],
                "wins": dados['Wins'],
                "headshots": dados['Headshots'],
                "enemies_flashed": dados['EnemiesFlashed'],
                "utility_damage": dados['UtilityDamage']
            }

            if response.data:
                atual = response.data[0]
                novos_dados["kills"] += atual.get('kills', 0)
                novos_dados["deaths"] += atual.get('deaths', 0)
                novos_dados["matches"] += atual.get('matches', 0)
                novos_dados["wins"] += atual.get('wins', 0)
                novos_dados["headshots"] += atual.get('headshots', 0)
                novos_dados["enemies_flashed"] += atual.get('enemies_flashed', 0)
                novos_dados["utility_damage"] += atual.get('utility_damage', 0)
                supabase.table('player_stats').update(novos_dados).eq('nickname', nick).execute()
            else:
                novos_dados["nickname"] = nick
                supabase.table('player_stats').insert(novos_dados).execute()
        
        contador += 1
        progresso.progress(contador / total)
    progresso.empty()

def processar_demo(arquivo_upload):
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo_upload.read())
    caminho_temp = tfile.name
    tfile.close()
    
    stats_partida = {nome: {"Kills": 0, "Deaths": 0, "Matches": 0, "Wins": 0, "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0} for nome in AMIGOS.keys()}
    sucesso = False
    
    try:
        parser = DemoParser(caminho_temp)
        
        # 1. Extração
        events_death = parser.parse_events(["player_death"])
        events_blind = parser.parse_events(["player_blind"])
        events_hurt = parser.parse_events(["player_hurt"])
        events_round = parser.parse_events(["round_end"])
        
        df_death = pd.DataFrame(events_death)
        df_blind = pd.DataFrame(events_blind)
        df_hurt = pd.DataFrame(events_hurt)
        df_round = pd.DataFrame(events_round)

        # --- DETETIVE DE COLUNAS (AUTO-CORREÇÃO) ---
        if not df_death.empty:
            cols = df_death.columns.tolist()
            st.info(f"📋 Colunas encontradas na demo: {cols}") # MOSTRA A LISTA NA TELA
            
            # Tenta achar o nome certo da coluna de ID
            col_atk = next((c for c in cols if c in ['attacker_steamid', 'attacker_xuid', 'attacker_player_id']), None)
            col_vic = next((c for c in cols if c in ['user_steamid', 'user_xuid', 'user_player_id']), None)
            
            if not col_atk or not col_vic:
                st.error(f"⚠️ IDs não encontrados! Colunas disponíveis: {cols}")
                return False
        else:
            col_atk, col_vic = 'attacker_steamid', 'user_steamid'

        # Conversão para texto
        for df in [df_death, df_blind, df_hurt]:
            if not df.empty and col_atk in df.columns: df[col_atk] = df[col_atk].astype(str)
            if not df.empty and col_vic in df.columns: df[col_vic] = df[col_vic].astype(str)

        # 2. Lógica de Vitória
        winning_team_num = None
        if not df_round.empty and 'winner' in df_round.columns:
            try:
                rounds_t = len(df_round[df_round['winner'] == 2])
                rounds_ct = len(df_round[df_round['winner'] == 3])
                winning_team_num = 2 if rounds_t > rounds_ct else 3
            except: pass

        # 3. Processamento com Nomes Dinâmicos
        for nome_exibicao, steam_id in AMIGOS.items():
            
            if not df_death.empty and col_atk in df_death.columns:
                # Kills
                meus_kills = df_death[df_death[col_atk] == steam_id]
                stats_partida[nome_exibicao]["Kills"] = len(meus_kills)
                if 'headshot' in meus_kills.columns:
                    stats_partida[nome_exibicao]["Headshots"] = len(meus_kills[meus_kills['headshot'] == True])
                
                # Deaths
                stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic] == steam_id])

            # Flashs
            if not df_blind.empty and col_atk in df_blind.columns:
                stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind[col_atk] == steam_id])

            # Dano
            if not df_hurt.empty and col_atk in df_hurt.columns and 'weapon' in df_hurt.columns and 'dmg_health' in df_hurt.columns:
                meu_dano = df_hurt[(df_hurt[col_atk] == steam_id) & (df_hurt['weapon'].isin(['hegrenade', 'inferno', 'incgrenade']))]
                stats_partida[nome_exibicao]["UtilityDamage"] = int(meu_dano['dmg_health'].sum())

            # Vitória
            if winning_team_num and not df_death.empty:
                # Tenta achar time
                player_team = None
                # Atacando
                if col_atk in df_death.columns and 'attacker_team_num' in df_death.columns:
                    last = df_death[df_death[col_atk] == steam_id]
                    if not last.empty: player_team = last.iloc[-1]['attacker_team_num']
                # Defendendo (se não achou)
                if not player_team and col_vic in df_death.columns and 'user_team_num' in df_death.columns:
                    last = df_death[df_death[col_vic] == steam_id]
                    if not last.empty: player_team = last.iloc[-1]['user_team_num']
                
                if player_team == winning_team_num:
                    stats_partida[nome_exibicao]["Wins"] = 1
            
            # Participação
            if stats_partida[nome_exibicao]["Kills"] > 0 or stats_partida[nome_exibicao]["Deaths"] > 0:
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True

        if sucesso:
            atualizar_banco(stats_partida)

    except Exception as e:
        st.error(f"Erro ao processar: {e}")
    finally:
        os.remove(caminho_temp)
    return sucesso

# --- 3. INTERFACE ---
st.title("🔥 CS2 Pro Ranking - Modo Detetive")

tab1, tab2 = st.tabs(["📤 Upload", "🏆 Ranking"])

with tab1:
    arquivo = st.file_uploader("Arquivo .dem", type=["dem"])
    if arquivo and st.button("🚀 Processar"):
        with st.spinner("Processando..."):
            if processar_demo(arquivo):
                st.success("Sucesso!")
                st.balloons()
            else:
                st.warning("Nenhum jogador encontrado ou demo incompatível.")

with tab2:
    if st.button("🔄 Atualizar"): st.rerun()
    response = supabase.table('player_stats').select("*").execute()
    if response.data:
        df = pd.DataFrame(response.data)
        for c in ['kills', 'deaths', 'matches', 'wins', 'headshots', 'utility_damage']:
            if c not in df.columns: df[c] = 0
        
        df['KD'] = df.apply(lambda x: x['kills']/x['deaths'] if x['deaths']>0 else x['kills'], axis=1)
        df['Win%'] = df.apply(lambda x: x['wins']/x['matches']*100 if x['matches']>0 else 0, axis=1)
        
        st.dataframe(df[['nickname', 'KD', 'Win%', 'kills', 'deaths', 'matches']], hide_index=True)
    else:
        st.info("Ranking vazio.")