import streamlit as st
import pandas as pd
import os
import tempfile
import hashlib
from supabase import create_client, Client
from demoparser2 import DemoParser

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="CS2 Pro Ranking", page_icon="🧬", layout="wide")

try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
except FileNotFoundError:
    st.error("❌ Erro: Secrets não encontrados.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- LISTA DE AMIGOS (Atualizada com as IDs da Imagem) ---
AMIGOS = {
    "Ph (Ph1L)": [
        "76561198301569089", # Main
        "76561198051052379"  # Zezé (Pego da sua imagem)
    ],
    "Pablo (Cyrax)": [
        "76561198143002755", # Main
        "76561198446160415"  # Cyrax (Pego da sua imagem)
    ],
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

def ler_evento(parser, nome_evento):
    try:
        dados = parser.parse_events([nome_evento])
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
    
    stats_partida = {nome: {"Kills": 0, "Deaths": 0, "Matches": 0, "Wins": 0, "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0} for nome in AMIGOS.keys()}
    sucesso = False
    
    try:
        parser = DemoParser(caminho_temp)
        
        # 1. LEITURA
        df_round = ler_evento(parser, "round_end")
        df_death = ler_evento(parser, "player_death")
        df_blind = ler_evento(parser, "player_blind")
        df_hurt = ler_evento(parser, "player_hurt")
        df_team = ler_evento(parser, "player_team") # O Evento Mágico

        # 2. COLUNAS DE ID
        col_atk = next((c for c in df_death.columns if c in ['attacker_steamid', 'attacker_xuid', 'attacker_steamid64']), None)
        col_vic = next((c for c in df_death.columns if c in ['user_steamid', 'user_xuid', 'user_steamid64']), None)
        
        # Coluna ID na troca de time (Geralmente user_steamid)
        col_team_id = next((c for c in df_team.columns if c in ['user_steamid', 'steamid', 'userid_steamid']), None)

        if not col_atk:
            st.error("Erro: IDs não encontrados.")
            return False

        # 3. LIMPEZA
        for df in [df_death, df_blind, df_hurt, df_team]:
            for col in df.columns:
                if 'steamid' in col or 'xuid' in col:
                    df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        # 4. TIMELINE DE TIMES (Baseado na sua imagem!)         # Se um jogador tem um evento no tick 73549 trocando de 2 para 3:
        # - Antes de 73549: Ele era 2.
        # - Depois de 73549: Ele é 3.
        
        player_timelines = {}
        
        if not df_team.empty and col_team_id:
            df_team = df_team.sort_values('tick')
            
            for _, row in df_team.iterrows():
                uid = row[col_team_id]
                new_team = normalizar_time(row.get('team'))
                old_team = normalizar_time(row.get('oldteam'))
                tick = row['tick']
                
                if uid and new_team:
                    if uid not in player_timelines:
                        player_timelines[uid] = []
                        # Se temos o 'oldteam', sabemos o time inicial!
                        if old_team:
                            player_timelines[uid].append({'tick': 0, 'team': old_team})
                    
                    player_timelines[uid].append({'tick': tick, 'team': new_team})

        # 5. ROUNDS
        rounds = []
        if not df_round.empty and 'winner' in df_round.columns:
            for _, row in df_round.iterrows():
                w = normalizar_time(row['winner'])
                if w: rounds.append({'tick': row['tick'], 'winner': w})

        # --- PROCESSAMENTO ---
        for nome_exibicao, lista_ids in AMIGOS.items():
            lista_ids = [str(uid).strip() for uid in lista_ids]
            
            # KILLS / DEATHS
            if not df_death.empty and col_atk:
                my_kills = df_death[df_death[col_atk].isin(lista_ids)]
                stats_partida[nome_exibicao]["Kills"] = len(my_kills)
                if 'headshot' in my_kills.columns:
                    stats_partida[nome_exibicao]["Headshots"] = len(my_kills[my_kills['headshot']==True])
                if col_vic:
                    stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic].isin(lista_ids)])

            # FLASH / DANO
            if not df_blind.empty:
                c_atk = next((c for c in df_blind.columns if 'attacker' in c), None)
                if c_atk: stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind[c_atk].isin(lista_ids)])
            
            if not df_hurt.empty:
                c_atk = next((c for c in df_hurt.columns if 'attacker' in c), None)
                if c_atk and 'weapon' in df_hurt.columns:
                    dmg = df_hurt[(df_hurt[c_atk].isin(lista_ids)) & (df_hurt['weapon'].isin(['hegrenade', 'inferno', 'incgrenade']))]
                    stats_partida[nome_exibicao]["UtilityDamage"] = int(dmg['dmg_health'].sum())

            # VITÓRIA (Lógica da Timeline)
            meus_rounds = 0
            total_rounds = 0
            
            # Acha a timeline deste jogador (procura por qualquer ID dele)
            minha_timeline = []
            for uid in lista_ids:
                if uid in player_timelines:
                    minha_timeline = player_timelines[uid]
                    break
            
            # Se não achou no player_team (talvez não trocou de time?), tenta usar kills como fallback
            if not minha_timeline and not df_death.empty:
                temp = []
                c_t = next((c for c in df_death.columns if 'attacker_team' in c or 'team_num' in c), None)
                if c_t:
                    ks = df_death[df_death[col_atk].isin(lista_ids)]
                    for _, r in ks.iterrows():
                        t = normalizar_time(r[c_t])
                        if t: temp.append({'tick': r['tick'], 'team': t})
                    if temp: minha_timeline = temp # Usa timeline de kills se a oficial falhar

            if rounds and minha_timeline:
                for r in rounds:
                    r_tick = r['tick']
                    r_winner = r['winner']
                    
                    # Qual era meu time neste round?
                    # Pega o último registro de time ANTES do round acabar
                    meu_time = None
                    estados_anteriores = [e for e in minha_timeline if e['tick'] <= r_tick]
                    if estados_anteriores:
                        meu_time = estados_anteriores[-1]['team']
                    
                    if meu_time == r_winner:
                        meus_rounds += 1
                    total_rounds += 1
            
            if total_rounds > 0 and meus_rounds > (total_rounds / 2):
                stats_partida[nome_exibicao]["Wins"] = 1

            if stats_partida[nome_exibicao]["Kills"] > 0 or stats_partida[nome_exibicao]["Deaths"] > 0:
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True

        if sucesso:
            atualizar_banco(stats_partida)
            registrar_demo(file_hash)
            return True
        else:
            st.warning("Nenhum stats encontrado para os IDs listados.")
            return False

    except Exception as e:
        st.error(f"Erro: {e}")
        return False
    finally:
        if os.path.exists(caminho_temp):
            os.remove(caminho_temp)

# --- 3. INTERFACE ---
st.title("🔥 CS2 Pro Ranking")

tab1, tab2 = st.tabs(["📤 Upload", "🏆 Ranking"])

with tab1:
    arquivo = st.file_uploader("Arquivo .dem", type=["dem"])
    if arquivo and st.button("🚀 Processar Demo"):
        with st.spinner("Processando..."):
            if processar_demo(arquivo):
                st.success("Dados salvos!")
                st.balloons()

with tab2:
    if st.button("🔄 Atualizar"): st.rerun()
    
    response = supabase.table('player_stats').select("*").execute()
    if response.data:
        df = pd.DataFrame(response.data)
        
        cols = ['kills', 'deaths', 'matches', 'wins', 'headshots', 'utility_damage', 'enemies_flashed']
        for c in cols: 
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