import streamlit as st
import pandas as pd
import os
import tempfile
import hashlib
from supabase import create_client, Client
from demoparser2 import DemoParser

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="CS2 Pro Ranking", page_icon="🎯", layout="wide")

try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
except FileNotFoundError:
    st.error("❌ Erro: Secrets não encontrados.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- LISTA DE AMIGOS ---
AMIGOS = {
    "Ph (Ph1L)": ["76561198301569089", "76561198051052379"],
    "Pablo (Cyrax)": ["76561198143002755", "76561198446160415"],
    "Bruno (Safadinha)": ["76561198187604726"],
    "Daniel (Ocharadas)": ["76561199062357951"],
    "LEO (Trewan)": ["76561198160033077"],
    "FERNANDO (Nandin)": ["76561198185508959"],
    "DG (dgtremsz)": ["76561199402154960"],
    "Arlon (M4CH)": ["76561197978110112"],
}

# --- 2. FUNÇÕES ---

def normalizar_time(valor):
    """2 = TR, 3 = CT"""
    try:
        s = str(valor).upper().strip().replace('.0', '')
        if s in ['CT', '3']: return 3
        if s in ['T', 'TERRORIST', '2']: return 2
        return None
    except: return None

def calcular_hash(arquivo_bytes):
    return hashlib.md5(arquivo_bytes).hexdigest()

def demo_ja_processada(file_hash):
    try:
        response = supabase.table('processed_matches').select('match_hash').eq('match_hash', file_hash).execute()
        return len(response.data) > 0
    except: return False

def registrar_demo(file_hash):
    try:
        supabase.table('processed_matches').insert({'match_hash': file_hash}).execute()
    except: pass

def extrair_dados_seguro(parser, evento, colunas_extra=None):
    try:
        # Pede explicitamente as colunas que precisamos
        dados = parser.parse_events([evento], other_props=colunas_extra)
        if isinstance(dados, list) and len(dados) > 0:
            return pd.DataFrame(dados[0][1])
        return pd.DataFrame(dados)
    except: return pd.DataFrame()

def atualizar_banco(stats_novos):
    progresso = st.progress(0)
    total = len(stats_novos)
    for i, (nick, dados) in enumerate(stats_novos.items()):
        if dados['Matches'] > 0:
            response = supabase.table('player_stats').select("*").eq('nickname', nick).execute()
            
            novos_dados = {
                "kills": dados['Kills'], "deaths": dados['Deaths'], "matches": dados['Matches'],
                "wins": dados['Wins'], "headshots": dados['Headshots'], 
                "enemies_flashed": dados['EnemiesFlashed'], "utility_damage": dados['UtilityDamage']
            }
            try:
                if response.data:
                    atual = response.data[0]
                    for k in novos_dados: novos_dados[k] += atual.get(k, 0)
                    supabase.table('player_stats').update(novos_dados).eq('nickname', nick).execute()
                else:
                    novos_dados["nickname"] = nick
                    supabase.table('player_stats').insert(novos_dados).execute()
            except Exception as e:
                st.error(f"Erro BD: {e}")
        progresso.progress((i + 1) / total)
    progresso.empty()

def processar_demo(arquivo_upload):
    arquivo_bytes = arquivo_upload.read()
    file_hash = calcular_hash(arquivo_bytes)
    
    if demo_ja_processada(file_hash):
        st.error("⛔ Demo Duplicada!")
        return False

    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo_bytes)
    caminho_temp = tfile.name
    tfile.close()
    
    # Inicializa stats
    stats_partida = {nome: {"Kills": 0, "Deaths": 0, "Matches": 0, "Wins": 0, "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0} for nome in AMIGOS.keys()}
    sucesso = False
    
    try:
        parser = DemoParser(caminho_temp)
        
        # 1. LEITURA REFORÇADA (Pede team_num explicitamente)
        # Round End: Winner
        df_round = extrair_dados_seguro(parser, "round_end", ["winner", "reason"])
        
        # Player Spawn: ESSENCIAL PARA SABER O TIME
        df_spawn = extrair_dados_seguro(parser, "player_spawn", ["team_num", "user_steamid"])
        
        # Combate
        df_death = extrair_dados_seguro(parser, "player_death", ["attacker_steamid", "user_steamid", "headshot", "attacker_team_num"])
        df_blind = extrair_dados_seguro(parser, "player_blind", ["attacker_steamid"])
        df_hurt = extrair_dados_seguro(parser, "player_hurt", ["attacker_steamid", "weapon", "dmg_health"])

        # Identificação de IDs
        col_spawn_id = 'user_steamid'
        col_atk_id = 'attacker_steamid'
        col_vic_id = 'user_steamid'

        # Limpeza de IDs (remove .0)
        for df in [df_spawn, df_death, df_blind, df_hurt]:
            for col in df.columns:
                if 'steamid' in col:
                    df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        # --- MAPA DE ROUNDS ---
        # Cria uma lista: Round 1 acabou no tick 1000, venceu TR (2)
        rounds_info = []
        if not df_round.empty and 'winner' in df_round.columns:
            for _, row in df_round.iterrows():
                w = normalizar_time(row['winner'])
                if w: rounds_info.append({'tick': row['tick'], 'winner': w})
        
        # --- MAPA DE TIMES DOS JOGADORES ---
        # Descobre qual time cada amigo estava EM CADA MOMENTO
        # player_teams[steamid] = [(tick, team), (tick, team)...]
        player_teams = {}
        
        if not df_spawn.empty and 'team_num' in df_spawn.columns:
            df_spawn = df_spawn.sort_values('tick')
            for _, row in df_spawn.iterrows():
                uid = row.get(col_spawn_id)
                team = normalizar_time(row.get('team_num'))
                if uid and team:
                    if uid not in player_teams: player_teams[uid] = []
                    player_teams[uid].append({'tick': row['tick'], 'team': team})

        # --- PROCESSAMENTO ---
        for nome_exibicao, lista_ids in AMIGOS.items():
            lista_ids = [str(uid).strip() for uid in lista_ids]
            
            # 1. STATS BÁSICOS
            if not df_death.empty and col_atk_id in df_death.columns:
                my_kills = df_death[df_death[col_atk_id].isin(lista_ids)]
                stats_partida[nome_exibicao]["Kills"] = len(my_kills)
                if 'headshot' in my_kills.columns:
                    stats_partida[nome_exibicao]["Headshots"] = len(my_kills[my_kills['headshot']==True])
                if col_vic_id in df_death.columns:
                    stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic_id].isin(lista_ids)])

            if not df_blind.empty and 'attacker_steamid' in df_blind.columns:
                stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind['attacker_steamid'].isin(lista_ids)])
            
            if not df_hurt.empty and 'attacker_steamid' in df_hurt.columns:
                dmg = df_hurt[(df_hurt['attacker_steamid'].isin(lista_ids)) & (df_hurt['weapon'].isin(['hegrenade', 'inferno', 'incgrenade']))]
                stats_partida[nome_exibicao]["UtilityDamage"] = int(dmg['dmg_health'].sum())

            # 2. CÁLCULO DE VITÓRIA (CONTABILIDADE ROUND A ROUND)
            meus_pontos = 0
            total_rounds_validos = 0
            
            # Pega o ID principal para checar o time (assume que todos os IDs do usuario jogam no mesmo time)
            meu_historico_times = []
            for uid in lista_ids:
                if uid in player_teams:
                    meu_historico_times = player_teams[uid]
                    break
            
            if rounds_info and meu_historico_times:
                for r in rounds_info:
                    r_tick = r['tick']
                    r_winner = r['winner']
                    
                    # Qual era meu time ANTES desse round acabar?
                    meu_time_no_round = None
                    
                    # Filtra spawns anteriores ao fim do round
                    historico_valido = [h for h in meu_historico_times if h['tick'] < r_tick]
                    if historico_valido:
                        meu_time_no_round = historico_valido[-1]['team'] # Pega o mais recente
                    
                    # Se eu estava no time que ganhou o round -> Ponto pra mim
                    if meu_time_no_round == r_winner:
                        meus_pontos += 1
                    
                    total_rounds_validos += 1

            # Regra da Vitória: Mais da metade dos rounds?
            # Ex: Ganhou 13 de 18 rounds -> Vitória
            if total_rounds_validos > 0 and meus_pontos > (total_rounds_validos / 2):
                stats_partida[nome_exibicao]["Wins"] = 1
                
            # Participação
            if stats_partida[nome_exibicao]["Kills"] > 0 or stats_partida[nome_exibicao]["Deaths"] > 0:
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True

        if sucesso:
            atualizar_banco(stats_partida)
            registrar_demo(file_hash)

    except Exception as e:
        st.error(f"Erro Fatal: {e}")
    finally:
        os.remove(caminho_temp)
    return sucesso

# --- 3. INTERFACE ---
st.title("🔥 CS2 Pro Ranking")

tab1, tab2 = st.tabs(["📤 Upload", "🏆 Ranking"])

with tab1:
    arquivo = st.file_uploader("Arquivo .dem", type=["dem"])
    if arquivo and st.button("🚀 Processar Demo"):
        with st.spinner("Computando round a round..."):
            if processar_demo(arquivo):
                st.success("Dados salvos!")
                st.balloons()

with tab2:
    if st.button("🔄 Atualizar"): st.rerun()
    
    response = supabase.table('player_stats').select("*").execute()
    if response.data:
        df = pd.DataFrame(response.data)
        
        cols_check = ['kills', 'deaths', 'matches', 'wins', 'headshots', 'utility_damage', 'enemies_flashed']
        for c in cols_check:
            if c not in df.columns: df[c] = 0
            
        df['KD'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        df['WinRate'] = df.apply(lambda x: (x['wins'] / x['matches']) if x['matches'] > 0 else 0.0, axis=1)
        df['HS%'] = df.apply(lambda x: (x['headshots'] / x['kills'] * 100) if x['kills'] > 0 else 0.0, axis=1)
        
        df = df.sort_values(by='KD', ascending=False)
        
        st.dataframe(
            df[['nickname', 'KD', 'WinRate', 'kills', 'deaths', 'HS%', 'enemies_flashed', 'utility_damage']],
            hide_index=True,
            column_config={
                "nickname": "Jogador",
                "KD": st.column_config.NumberColumn("K/D", format="%.2f ⭐"),
                "WinRate": st.column_config.ProgressColumn("Win Rate", format="%.0f%%", min_value=0, max_value=1),
                "HS%": st.column_config.NumberColumn("HS %", format="%.1f%% 🎯"),
                "enemies_flashed": st.column_config.NumberColumn("Cegos 💡"),
                "utility_damage": st.column_config.NumberColumn("Dano Util 💣"),
                "kills": "Kills",
                "deaths": "Mortes"
            },
            use_container_width=True
        )
    else:
        st.info("Ranking vazio.")