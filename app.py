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
    """Garante que o time seja sempre '2' (TR) ou '3' (CT)"""
    try:
        if pd.isna(valor): return None
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
        # Verifica se o evento existe antes de tentar extrair
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
    # 1. Check Duplicidade
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
        df_spawn = extrair_dados(parser, "player_spawn")

        # Detecção de Colunas
        col_atk, col_vic = None, None
        if not df_death.empty:
            cols = df_death.columns.tolist()
            possiveis = ['attacker_steamid', 'attacker_xuid', 'attacker_player_id', 'attacker_steamid64']
            col_atk = next((c for c in cols if c in possiveis), None)
            possiveis_vic = ['user_steamid', 'user_xuid', 'user_player_id', 'user_steamid64']
            col_vic = next((c for c in cols if c in possiveis_vic), None)

        col_spawn = None
        if not df_spawn.empty:
            cols_spawn = df_spawn.columns.tolist()
            col_spawn = next((c for c in cols_spawn if c in ['user_steamid', 'steamid', 'player_steamid', 'user_xuid']), None)

        if not col_atk:
            st.warning("⚠️ IDs não encontrados na demo.")
            return False

        # Limpeza de IDs
        for df in [df_death, df_blind, df_hurt, df_spawn]:
            for c in [col_atk, col_vic, col_spawn]:
                if c and c in df.columns:
                    df[c] = df[c].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        # --- LÓGICA DE VITÓRIA ---
        # Filtra apenas rounds válidos (ignora warmup/empates)
        rounds_validos = pd.DataFrame()
        if not df_round.empty and 'winner' in df_round.columns:
            # Mantém apenas onde vencedor foi 2 (TR) ou 3 (CT)
            df_round['winner_norm'] = df_round['winner'].apply(normalizar_time)
            rounds_validos = df_round.dropna(subset=['winner_norm'])

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

            # VITÓRIA (Algoritmo Refinado)
            rounds_ganhos = 0
            total_rounds_validos = 0
            
            if not rounds_validos.empty:
                for _, row in rounds_validos.iterrows():
                    tick = row['tick']
                    winner = row['winner_norm']
                    
                    # Procura o time do jogador neste momento
                    my_team = None
                    
                    # 1. Tenta pelo Spawn (mais recente antes do fim do round)
                    if not df_spawn.empty and col_spawn:
                        spawns = df_spawn[(df_spawn['tick'] < tick) & (df_spawn[col_spawn].isin(lista_ids))]
                        if not spawns.empty:
                            last = spawns.iloc[-1]
                            # Tenta várias colunas de time
                            for t_col in ['team_num', 'user_team_num', 'player_team_num']:
                                if t_col in last:
                                    t = normalizar_time(last[t_col])
                                    if t: 
                                        my_team = t
                                        break
                    
                    # 2. Se falhar, tenta pela Morte/Kill (mais recente antes do fim do round)
                    if not my_team and not df_death.empty:
                        events = df_death[
                            (df_death['tick'] < tick) & 
                            ((df_death[col_atk].isin(lista_ids)) | (df_death[col_vic].isin(lista_ids)))
                        ]
                        if not events.empty:
                            last = events.iloc[-1]
                            if last[col_atk] in lista_ids and 'attacker_team_num' in last:
                                my_team = normalizar_time(last['attacker_team_num'])
                            elif last[col_vic] in lista_ids and 'user_team_num' in last:
                                my_team = normalizar_time(last['user_team_num'])

                    if my_team == winner:
                        rounds_ganhos += 1
                    
                    total_rounds_validos += 1

            # Regra: Ganhou a maioria dos rounds VÁLIDOS?
            if total_rounds_validos > 0 and rounds_ganhos > (total_rounds_validos / 2):
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
    arquivo = st.file_uploader("Arquivo .dem", type=["dem"])
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
            
        # Cálculos
        df['K/D'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        df['Win%'] = df.apply(lambda x: (x['wins'] / x['matches']), axis=1) # Mantém decimal para formatar depois
        df['HS%'] = df.apply(lambda x: (x['headshots'] / x['kills']), axis=1)
        
        df = df.sort_values(by='K/D', ascending=False)
        
        # --- TABELA VISUAL (CORRIGIDA) ---
        st.dataframe(
            df[['nickname', 'K/D', 'Win%', 'kills', 'deaths', 'HS%', 'enemies_flashed', 'utility_damage']],
            hide_index=True,
            column_config={
                "nickname": "Jogador",
                "K/D": st.column_config.NumberColumn("K/D", format="%.2f ⭐"),
                "Win%": st.column_config.ProgressColumn(
                    "Win Rate", 
                    format="%.0f%%", 
                    min_value=0, 
                    max_value=1
                ),
                "HS%": st.column_config.NumberColumn("HS %", format="%.4f%% 🎯"),
                "enemies_flashed": st.column_config.NumberColumn("Cegos 💡"),
                "utility_damage": st.column_config.NumberColumn("Dano Util 💣"),
                "kills": "Kills",
                "deaths": "Mortes"
            },
            use_container_width=True
        )
    else:
        st.info("Ranking vazio.")