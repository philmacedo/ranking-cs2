import streamlit as st
import pandas as pd
import os
import tempfile
from supabase import create_client, Client
from demoparser2 import DemoParser

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="CS2 Pro Ranking", page_icon="🔥", layout="wide")

# Conexão Supabase
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
except FileNotFoundError:
    st.error("❌ Erro: Secrets não encontrados.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- LISTA DE AMIGOS (Nome: SteamID64) ---
AMIGOS = {
    "Ph (Ph1L)": "76561198301569089", 
    "Pablo (Cyrax)": "76561198143002755",  # pablo
    "Bruno (Safadinha)": "76561198187604726",
    "Daniel (Ocharadas)": "76561199062357951",
    "LEO (Trewan)": "76561198160033077",
    "FERNANDO (Nandin)": "76561198185508959",
    "DG (dgtremsz)":"76561199402154960",
    "Arlon (M4CH)": "76561197978110112",
}

# --- 2. FUNÇÕES ---

def atualizar_banco(stats_novos):
    """Envia os dados acumulados para a nuvem"""
    progresso = st.progress(0)
    total = len(stats_novos)
    contador = 0

    for nick, dados in stats_novos.items():
        if dados['Matches'] > 0:
            response = supabase.table('player_stats').select("*").eq('nickname', nick).execute()
            
            if response.data:
                atual = response.data[0]
                novos_dados = {
                    "kills": atual['kills'] + dados['Kills'],
                    "deaths": atual['deaths'] + dados['Deaths'],
                    "matches": atual['matches'] + dados['Matches'],
                    "wins": atual.get('wins', 0) + dados['Wins'],
                    "headshots": atual.get('headshots', 0) + dados['Headshots'],
                    "enemies_flashed": atual.get('enemies_flashed', 0) + dados['EnemiesFlashed'],
                    "utility_damage": atual.get('utility_damage', 0) + dados['UtilityDamage']
                }
                supabase.table('player_stats').update(novos_dados).eq('nickname', nick).execute()
            else:
                primeiros_dados = {
                    "nickname": nick,
                    "kills": dados['Kills'],
                    "deaths": dados['Deaths'],
                    "matches": dados['Matches'],
                    "wins": dados['Wins'],
                    "headshots": dados['Headshots'],
                    "enemies_flashed": dados['EnemiesFlashed'],
                    "utility_damage": dados['UtilityDamage']
                }
                supabase.table('player_stats').insert(primeiros_dados).execute()
        
        contador += 1
        progresso.progress(contador / total)
    progresso.empty()

def processar_demo(arquivo_upload):
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo_upload.read())
    caminho_temp = tfile.name
    tfile.close()
    
    # Inicializa estatísticas zeradas
    stats_partida = {nome: {
        "Kills": 0, "Deaths": 0, "Matches": 0, "Wins": 0, 
        "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0
    } for nome in AMIGOS.keys()}
    
    sucesso = False
    
    try:
        parser = DemoParser(caminho_temp)
        
        # 1. Extração de Eventos
        events_death = parser.parse_events(["player_death"])
        events_blind = parser.parse_events(["player_blind"])
        events_hurt = parser.parse_events(["player_hurt"])
        events_round = parser.parse_events(["round_end"])
        
        # DataFrames
        df_death = pd.DataFrame(events_death)
        df_blind = pd.DataFrame(events_blind)
        df_hurt = pd.DataFrame(events_hurt)
        df_round = pd.DataFrame(events_round)

        # --- ADICIONE ISTO AQUI PARA DEBUGAR ---
        st.write("🔍 Debug - Colunas encontradas na Morte:", df_death.columns.tolist() if not df_death.empty else "Tabela Vazia")
        st.write("🔍 Debug - Exemplo de dados:", df_death.head(2) if not df_death.empty else "Sem dados")
        # ---------------------------------------

        # Conversão de IDs para Texto (Segurança Crítica)
        for df in [df_death, df_blind, df_hurt]:
            if not df.empty and 'attacker_steamid' in df.columns:
                df['attacker_steamid'] = df['attacker_steamid'].astype(str)
            if not df.empty and 'user_steamid' in df.columns:
                df['user_steamid'] = df['user_steamid'].astype(str)

        # 2. Lógica de Vitória (Quem ganhou?)
        winning_team_num = None
        if not df_round.empty and 'winner' in df_round.columns:
            try:
                # 2 = Terrorist, 3 = CT
                rounds_t = len(df_round[df_round['winner'] == 2])
                rounds_ct = len(df_round[df_round['winner'] == 3])
                if rounds_t > rounds_ct: winning_team_num = 2
                elif rounds_ct > rounds_t: winning_team_num = 3
            except: pass

        # 3. Processamento Jogador por Jogador
        for nome_exibicao, steam_id in AMIGOS.items():
            
            # --- A. COMBATE (Kills/Deaths/HS) ---
            if not df_death.empty:
                # Kills (Verifica se attacker existe para não pegar suicídio)
                if 'attacker_steamid' in df_death.columns:
                    meus_kills = df_death[df_death['attacker_steamid'] == steam_id]
                    stats_partida[nome_exibicao]["Kills"] = len(meus_kills)
                    
                    if 'headshot' in meus_kills.columns:
                        stats_partida[nome_exibicao]["Headshots"] = len(meus_kills[meus_kills['headshot'] == True])

                # Deaths (Verifica user existe)
                if 'user_steamid' in df_death.columns:
                    stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death['user_steamid'] == steam_id])

            # --- B. FLASHS (Cegueira) ---
            if not df_blind.empty and 'attacker_steamid' in df_blind.columns:
                stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind['attacker_steamid'] == steam_id])

            # --- C. DANO DE GRANADA ---
            # Requer attacker, weapon e dmg_health
            if not df_hurt.empty:
                cols_necessarias = ['attacker_steamid', 'weapon', 'dmg_health']
                # Só processa se todas as colunas existirem
                if all(col in df_hurt.columns for col in cols_necessarias):
                    granadas = ['hegrenade', 'inferno', 'incgrenade']
                    meu_dano = df_hurt[
                        (df_hurt['attacker_steamid'] == steam_id) & 
                        (df_hurt['weapon'].isin(granadas))
                    ]
                    stats_partida[nome_exibicao]["UtilityDamage"] = int(meu_dano['dmg_health'].sum())

            # --- D. VITÓRIAS ---
            # Tenta inferir o time do jogador baseado nas kills/mortes
            if winning_team_num and not df_death.empty:
                player_team = None
                
                # Procura time onde atacou
                if 'attacker_steamid' in df_death.columns and 'attacker_team_num' in df_death.columns:
                    last_atk = df_death[df_death['attacker_steamid'] == steam_id]
                    if not last_atk.empty:
                        player_team = last_atk.iloc[-1]['attacker_team_num']
                
                # Procura time onde morreu (fallback)
                if player_team is None and 'user_steamid' in df_death.columns and 'user_team_num' in df_death.columns:
                    last_vic = df_death[df_death['user_steamid'] == steam_id]
                    if not last_vic.empty:
                        player_team = last_vic.iloc[-1]['user_team_num']

                if player_team == winning_team_num:
                    stats_partida[nome_exibicao]["Wins"] = 1
            
            # --- E. PARTICIPAÇÃO ---
            jogou = (stats_partida[nome_exibicao]["Kills"] > 0) or \
                    (stats_partida[nome_exibicao]["Deaths"] > 0)
            
            if jogou:
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
st.title("🔥 CS2 Pro Ranking")

tab1, tab2 = st.tabs(["📤 Upload", "🏆 Ranking Completo"])

with tab1:
    st.write("Suba a demo. O sistema calcula Kills, HS, Dano de Granada e Vitórias.")
    arquivo = st.file_uploader("Arquivo .dem", type=["dem"])
    
    if arquivo is not None:
        if st.button("🚀 Processar Demo"):
            with st.spinner("Processando..."):
                if processar_demo(arquivo):
                    st.success("Sucesso! Estatísticas salvas.")
                    st.balloons()
                else:
                    st.warning("Demo processada, mas nenhum jogador da lista foi encontrado.")

with tab2:
    if st.button("🔄 Atualizar Tabela"):
        st.rerun()
    
    response = supabase.table('player_stats').select("*").execute()
    if response.data:
        df = pd.DataFrame(response.data)
        
        # Garante colunas (Preenche com 0 se faltar algo no banco)
        for col in ['kills', 'deaths', 'matches', 'wins', 'headshots', 'utility_damage', 'enemies_flashed']:
            if col not in df.columns: df[col] = 0

        # Cálculos Finais
        df['KD'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        df['WinRate'] = df.apply(lambda x: (x['wins'] / x['matches'] * 100) if x['matches'] > 0 else 0, axis=1)
        df['HS%'] = df.apply(lambda x: (x['headshots'] / x['kills'] * 100) if x['kills'] > 0 else 0, axis=1)
        
        df = df.sort_values(by='KD', ascending=False)
        
        st.dataframe(
            df[['nickname', 'KD', 'WinRate', 'wins', 'matches', 'kills', 'HS%', 'utility_damage']],
            hide_index=True,
            column_config={
                "nickname": "Jogador",
                "KD": st.column_config.NumberColumn("K/D", format="%.2f ⭐"),
                "WinRate": st.column_config.NumberColumn("Win %", format="%.0f%% 🏆"),
                "utility_damage": st.column_config.NumberColumn("Dano Util.", format="%.0f 💣"),
            },
            use_container_width=True
        )
    else:
        st.info("Ranking vazio.")