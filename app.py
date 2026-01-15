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
    "PH": "76561198301569089", 
    "Pablo(Cyrax)": "76561198143002755",
    # Adicione os outros...
}

# --- 2. FUNÇÕES ---

def atualizar_banco(stats_novos):
    """Envia os dados acumulados para a nuvem"""
    progresso = st.progress(0)
    total = len(stats_novos)
    contador = 0

    for nick, dados in stats_novos.items():
        if dados['Matches'] > 0:
            # Busca jogador no banco
            response = supabase.table('player_stats').select("*").eq('nickname', nick).execute()
            
            if response.data:
                atual = response.data[0]
                # Soma tudo (Antigo + Novo)
                novos_dados = {
                    "kills": atual['kills'] + dados['Kills'],
                    "deaths": atual['deaths'] + dados['Deaths'],
                    "matches": atual['matches'] + dados['Matches'],
                    "wins": atual.get('wins', 0) + dados['Wins'],  # <--- Agora soma vitórias reais
                    "headshots": atual.get('headshots', 0) + dados['Headshots'],
                    "enemies_flashed": atual.get('enemies_flashed', 0) + dados['EnemiesFlashed'],
                    "utility_damage": atual.get('utility_damage', 0) + dados['UtilityDamage']
                }
                supabase.table('player_stats').update(novos_dados).eq('nickname', nick).execute()
            else:
                # Cria novo
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
    
    # Estrutura zerada
    stats_partida = {nome: {
        "Kills": 0, "Deaths": 0, "Matches": 0, "Wins": 0, 
        "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0
    } for nome in AMIGOS.keys()}
    
    sucesso = False
    
    try:
        parser = DemoParser(caminho_temp)
        
        # 1. PEGAR TODOS OS EVENTOS
        # Adicionamos 'player_team' se disponível, ou inferimos pelo player_death
        events_death = parser.parse_events(["player_death"])
        events_blind = parser.parse_events(["player_blind"])
        events_hurt = parser.parse_events(["player_hurt"])
        events_round = parser.parse_events(["round_end"]) # Essencial para vitória
        
        # DataFrames
        df_death = pd.DataFrame(events_death)
        df_blind = pd.DataFrame(events_blind)
        df_hurt = pd.DataFrame(events_hurt)
        df_round = pd.DataFrame(events_round)

        # Conversão de IDs para Texto
        for df in [df_death, df_blind, df_hurt]:
            if not df.empty and 'attacker_steamid' in df.columns:
                df['attacker_steamid'] = df['attacker_steamid'].astype(str)
            if not df.empty and 'user_steamid' in df.columns:
                df['user_steamid'] = df['user_steamid'].astype(str)

        # --- LÓGICA DE VITÓRIA (QUEM GANHOU?) ---
        winning_team_num = None
        
        if not df_round.empty and 'winner' in df_round.columns:
            # Conta rounds ganhos
            # CS2: Team 2 = Terrorist, Team 3 = Counter-Terrorist
            rounds_t = len(df_round[df_round['winner'] == 2])
            rounds_ct = len(df_round[df_round['winner'] == 3])
            
            # Quem fez mais pontos ganhou
            if rounds_t > rounds_ct:
                winning_team_num = 2
            elif rounds_ct > rounds_t:
                winning_team_num = 3
            else:
                winning_team_num = 0 # Empate

        # --- PROCESSAMENTO POR JOGADOR ---
        for nome_exibicao, steam_id in AMIGOS.items():
            
            # --- A. COMBATE BÁSICO ---
            if not df_death.empty:
                meus_kills = df_death[df_death['attacker_steamid'] == steam_id]
                stats_partida[nome_exibicao]["Kills"] = len(meus_kills)
                stats_partida[nome_exibicao]["Headshots"] = len(meus_kills[meus_kills['headshot'] == True])
                stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death['user_steamid'] == steam_id])

            # --- B. FLASHS ---
            if not df_blind.empty:
                stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind['attacker_steamid'] == steam_id])

            # --- C. DANO DE GRANADA ---
            if not df_hurt.empty and 'weapon' in df_hurt.columns:
                granadas = ['hegrenade', 'inferno', 'incgrenade']
                meu_dano = df_hurt[
                    (df_hurt['attacker_steamid'] == steam_id) & 
                    (df_hurt['weapon'].isin(granadas))
                ]
                stats_partida[nome_exibicao]["UtilityDamage"] = int(meu_dano['dmg_health'].sum())

            # --- D. VITÓRIA ---
            # Precisamos saber em que time o amigo estava.
            # Vamos olhar a última vez que ele apareceu num evento de morte (matando ou morrendo)
            # para pegar o 'team_num' dele mais recente.
            
            player_team = None
            if not df_death.empty:
                # Procura eventos onde ele matou
                last_atk = df_death[df_death['attacker_steamid'] == steam_id]
                if not last_atk.empty:
                    # Tenta pegar attacker_team_num (varia nome as vezes)
                    if 'attacker_team_num' in last_atk.columns:
                        player_team = last_atk.iloc[-1]['attacker_team_num']
                
                # Se ainda não achou, procura onde morreu
                if player_team is None:
                    last_vic = df_death[df_death['user_steamid'] == steam_id]
                    if not last_vic.empty:
                        if 'user_team_num' in last_vic.columns:
                            player_team = last_vic.iloc[-1]['user_team_num']

            # Se achamos o time dele e temos um vencedor da partida
            if player_team and winning_team_num:
                if player_team == winning_team_num:
                    stats_partida[nome_exibicao]["Wins"] = 1
            
            # --- E. CHECK DE PARTICIPAÇÃO ---
            jogou = (stats_partida[nome_exibicao]["Kills"] > 0) or \
                    (stats_partida[nome_exibicao]["Deaths"] > 0)
            
            if jogou:
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True

        if sucesso:
            atualizar_banco(stats_partida)

    except Exception as e:
        st.error(f"Erro ao processar (Detalhe): {e}")
    finally:
        os.remove(caminho_temp)
        
    return sucesso

# --- 3. INTERFACE ---
st.title("🔥 CS2 Pro Ranking")

tab1, tab2 = st.tabs(["📤 Upload", "🏆 Ranking Completo"])

with tab1:
    st.write("Suba a demo. O sistema calcula Kills, HS, Dano de Granada e **Vitórias**.")
    arquivo = st.file_uploader("Arquivo .dem", type=["dem"])
    
    if arquivo is not None:
        if st.button("🚀 Processar Demo"):
            with st.spinner("Calculando vencedor da partida..."):
                if processar_demo(arquivo):
                    st.success("Partida computada com sucesso!")
                    st.balloons()
                else:
                    st.warning("Nenhum jogador da lista foi encontrado na demo.")

with tab2:
    if st.button("🔄 Atualizar Tabela"):
        st.rerun()
    
    response = supabase.table('player_stats').select("*").execute()
    if response.data:
        df = pd.DataFrame(response.data)
        
        # Preenchimento de segurança
        cols_check = ['kills', 'deaths', 'matches', 'wins', 'headshots', 'utility_damage', 'enemies_flashed']
        for c in cols_check:
            if c not in df.columns: df[c] = 0

        # Cálculos
        df['KD'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        df['WinRate'] = df.apply(lambda x: (x['wins'] / x['matches'] * 100) if x['matches'] > 0 else 0, axis=1)
        df['HS%'] = df.apply(lambda x: (x['headshots'] / x['kills'] * 100) if x['kills'] > 0 else 0, axis=1)
        
        # Ordenação
        df = df.sort_values(by='KD', ascending=False)
        
        # Exibição
        cols = ['nickname', 'KD', 'WinRate', 'wins', 'matches', 'kills']
        
        st.dataframe(
            df[cols],
            hide_index=True,
            column_config={
                "nickname": "Jogador",
                "KD": st.column_config.NumberColumn("K/D", format="%.2f ⭐"),
                "WinRate": st.column_config.NumberColumn("Win Rate", format="%.1f%% 🏆"),
                "wins": "Vitórias",
                "matches": "Partidas",
                "kills": "Kills",
            },
            use_container_width=True
        )
    else:
        st.info("Ranking vazio.")