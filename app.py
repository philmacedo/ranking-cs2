import streamlit as st
import pandas as pd
import os
import tempfile
import hashlib
from supabase import create_client, Client
from demoparser2 import DemoParser

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="CS2 Pro Ranking", page_icon="🏆", layout="wide")

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
    """Retorna '2' para TR e '3' para CT"""
    try:
        s = str(valor).upper().strip().replace('.0', '')
        if s in ['CT', '3']: return '3'
        if s in ['T', 'TERRORIST', '2']: return '2'
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

def extrair_dados(parser, evento):
    try:
        # Verifica se o evento existe na demo
        eventos_disponiveis = parser.list_game_events()
        if evento not in eventos_disponiveis: return pd.DataFrame()

        dados = parser.parse_events([evento])
        if isinstance(dados, list) and len(dados) > 0 and isinstance(dados[0], tuple):
            return pd.DataFrame(dados[0][1])
        if isinstance(dados, pd.DataFrame): return dados
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
                st.error(f"Erro ao salvar {nick}: {e}")
        progresso.progress((i + 1) / total)
    progresso.empty()

def processar_demo(arquivo_upload):
    # 1. Check Hash
    arquivo_bytes = arquivo_upload.read()
    file_hash = calcular_hash(arquivo_bytes)
    
    if demo_ja_processada(file_hash):
        st.error("⛔ Demo Duplicada! Esta partida já foi computada.")
        return False

    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo_bytes)
    caminho_temp = tfile.name
    tfile.close()
    
    stats_partida = {nome: {"Kills": 0, "Deaths": 0, "Matches": 0, "Wins": 0, "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0} for nome in AMIGOS.keys()}
    sucesso = False
    
    try:
        parser = DemoParser(caminho_temp)
        
        # Leitura
        df_death = extrair_dados(parser, "player_death")
        df_blind = extrair_dados(parser, "player_blind")
        df_hurt = extrair_dados(parser, "player_hurt")
        df_round = extrair_dados(parser, "round_end")
        
        # Colunas ID
        col_atk, col_vic = None, None
        if not df_death.empty:
            cols = df_death.columns.tolist()
            possiveis = ['attacker_steamid', 'attacker_xuid', 'attacker_player_id', 'attacker_steamid64']
            col_atk = next((c for c in cols if c in possiveis), None)
            possiveis_vic = ['user_steamid', 'user_xuid', 'user_player_id', 'user_steamid64']
            col_vic = next((c for c in cols if c in possiveis_vic), None)

        if not col_atk:
            st.warning("⚠️ IDs não encontrados na demo.")
            return False

        # Limpeza IDs
        for df in [df_death, df_blind, df_hurt]:
            for c in [col_atk, col_vic]:
                if c and c in df.columns:
                    df[c] = df[c].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        # --- QUEM GANHOU A PARTIDA? (SIMPLIFICADO) ---
        winning_team = None
        if not df_round.empty and 'winner' in df_round.columns:
            # Conta rounds ganhos por cada lado
            rounds_tr = len(df_round[df_round['winner'].apply(normalizar_time) == '2'])
            rounds_ct = len(df_round[df_round['winner'].apply(normalizar_time) == '3'])
            
            if rounds_tr > rounds_ct: winning_team = '2'
            elif rounds_ct > rounds_tr: winning_team = '3'

        # PROCESSAMENTO
        for nome_exibicao, lista_ids in AMIGOS.items():
            lista_ids = [str(uid).strip() for uid in lista_ids]
            
            # Combate
            if not df_death.empty and col_atk in df_death.columns:
                meus_kills = df_death[df_death[col_atk].isin(lista_ids)]
                stats_partida[nome_exibicao]["Kills"] = len(meus_kills)
                if 'headshot' in meus_kills.columns:
                    stats_partida[nome_exibicao]["Headshots"] = len(meus_kills[meus_kills['headshot'] == True])
                if col_vic in df_death.columns:
                    stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic].isin(lista_ids)])

            # Cegos
            if not df_blind.empty and col_atk in df_blind.columns:
                stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind[col_atk].isin(lista_ids)])
            
            # Dano
            if not df_hurt.empty and col_atk in df_hurt.columns:
                dmg = df_hurt[(df_hurt[col_atk].isin(lista_ids)) & (df_hurt['weapon'].isin(['hegrenade', 'inferno', 'incgrenade']))]
                stats_partida[nome_exibicao]["UtilityDamage"] = int(dmg['dmg_health'].sum())

            # VITÓRIA (Lógica: Qual foi o time dele na última vez que apareceu?)
            if winning_team and not df_death.empty:
                # Procura o último evento onde ele aparece (Matou ou Morreu)
                last_event = None
                
                # Filtra eventos dele
                my_events = df_death[
                    (df_death[col_atk].isin(lista_ids)) | 
                    (df_death[col_vic].isin(lista_ids))
                ].sort_values('tick')
                
                if not my_events.empty:
                    last_row = my_events.iloc[-1]
                    # Tenta descobrir o time dele nessa última aparição
                    my_team = None
                    if last_row[col_atk] in lista_ids and 'attacker_team_num' in last_row:
                        my_team = normalizar_time(last_row['attacker_team_num'])
                    elif last_row[col_vic] in lista_ids and 'user_team_num' in last_row:
                        my_team = normalizar_time(last_row['user_team_num'])
                    
                    if my_team == winning_team:
                        stats_partida[nome_exibicao]["Wins"] = 1

            # Participação
            if stats_partida[nome_exibicao]["Kills"] > 0 or stats_partida[nome_exibicao]["Deaths"] > 0:
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True

        if sucesso:
            atualizar_banco(stats_partida)
            registrar_demo(file_hash)

    except Exception as e:
        st.error(f"Erro no processamento: {e}")
    finally:
        os.remove(caminho_temp)
    return sucesso

# --- 3. INTERFACE ---
st.title("🔥 CS2 Pro Ranking")

tab1, tab2 = st.tabs(["📤 Upload", "🏆 Ranking"])

with tab1:
    arquivo = st.file_uploader("Upload do Arquivo .dem", type=["dem"])
    if arquivo and st.button("🚀 Processar Demo"):
        with st.spinner("Analisando partida..."):
            if processar_demo(arquivo):
                st.success("Demo processada com sucesso!")
                st.balloons()

with tab2:
    if st.button("🔄 Atualizar Tabela"): st.rerun()
    
    response = supabase.table('player_stats').select("*").execute()
    if response.data:
        df = pd.DataFrame(response.data)
        
        # Garante colunas
        cols_check = ['kills', 'deaths', 'matches', 'wins', 'headshots', 'utility_damage', 'enemies_flashed']
        for c in cols_check:
            if c not in df.columns: df[c] = 0
            
        # Cálculos de Rate
        # KD (Sem a barra para não dar erro no sort)
        df['KD'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        
        # Win Rate (0 a 1 para barra de progresso)
        df['WinRate'] = df.apply(lambda x: (x['wins'] / x['matches']) if x['matches'] > 0 else 0, axis=1)
        
        # HS Rate (Multiplicado por 100 para aparecer bonito no NumberColumn)
        df['HS%'] = df.apply(lambda x: (x['headshots'] / x['kills'] * 100) if x['kills'] > 0 else 0, axis=1)
        
        # Ordenação
        df = df.sort_values(by='KD', ascending=False)
        
        # --- TABELA VISUAL ---
        st.dataframe(
            df[['nickname', 'KD', 'WinRate', 'kills', 'deaths', 'HS%', 'enemies_flashed', 'utility_damage']],
            hide_index=True,
            column_config={
                "nickname": "Jogador",
                "KD": st.column_config.NumberColumn(
                    "K/D", 
                    format="%.2f ⭐"
                ),
                "WinRate": st.column_config.ProgressColumn(
                    "Win Rate", 
                    format="%.0f%%", 
                    min_value=0, 
                    max_value=1
                ),
                "HS%": st.column_config.NumberColumn(
                    "HS %", 
                    format="%.2f%% 🎯"
                ),
                "enemies_flashed": st.column_config.NumberColumn("Cegos 💡"),
                "utility_damage": st.column_config.NumberColumn("Dano Util 💣"),
                "kills": "Kills",
                "deaths": "Mortes"
            },
            use_container_width=True
        )
    else:
        st.info("Ranking vazio.")