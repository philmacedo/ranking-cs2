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
    s = str(valor).upper().strip()
    if s in ['CT', '3', '3.0']: return '3'
    if s in ['T', 'TERRORIST', '2', '2.0']: return '2'
    return None

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
    # Proteção: Verifica se o evento existe na demo antes de tentar ler
    try:
        # Pega lista de eventos disponíveis nesta demo específica
        eventos_disponiveis = parser.list_game_events()
        if evento not in eventos_disponiveis:
            return pd.DataFrame() # Retorna vazio se não existir
            
        dados = parser.parse_events([evento])
        if isinstance(dados, list) and len(dados) > 0 and isinstance(dados[0], tuple):
            return pd.DataFrame(dados[0][1])
        if isinstance(dados, pd.DataFrame): return dados
        return pd.DataFrame(dados)
    except:
        return pd.DataFrame()

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
                    for k in novos_dados: 
                        novos_dados[k] += atual.get(k, 0)
                    supabase.table('player_stats').update(novos_dados).eq('nickname', nick).execute()
                else:
                    novos_dados["nickname"] = nick
                    supabase.table('player_stats').insert(novos_dados).execute()
            except Exception as e:
                st.error(f"Erro ao salvar {nick}: {e}")
        progresso.progress((i + 1) / total)
    progresso.empty()

def processar_demo(arquivo_upload):
    arquivo_bytes = arquivo_upload.read()
    file_hash = calcular_hash(arquivo_bytes)
    
    if demo_ja_processada(file_hash):
        st.error("⛔ Demo já processada anteriormente!")
        return False

    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo_bytes)
    caminho_temp = tfile.name
    tfile.close()
    
    stats_partida = {nome: {"Kills": 0, "Deaths": 0, "Matches": 0, "Wins": 0, "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0} for nome in AMIGOS.keys()}
    sucesso = False
    
    try:
        parser = DemoParser(caminho_temp)
        
        # 1. Eventos Básicos
        df_death = extrair_dados(parser, "player_death")
        df_blind = extrair_dados(parser, "player_blind")
        df_hurt = extrair_dados(parser, "player_hurt")
        
        # 2. Eventos de Vitória (Usa o conhecimento do repo LaihoE)
        df_round = extrair_dados(parser, "round_end")
        df_match_end = extrair_dados(parser, "cs_win_panel_match") # O Juiz Final
        df_spawn = extrair_dados(parser, "player_spawn") # O Tira-Teima de Times

        # Detecção de Colunas
        col_atk, col_vic = None, None
        if not df_death.empty:
            cols = df_death.columns.tolist()
            possiveis_atk = ['attacker_steamid', 'attacker_xuid', 'attacker_player_id', 'attacker_steamid64']
            possiveis_vic = ['user_steamid', 'user_xuid', 'user_player_id', 'user_steamid64']
            col_atk = next((c for c in cols if c in possiveis_atk), None)
            col_vic = next((c for c in cols if c in possiveis_vic), None)
            
        col_spawn_id = None
        if not df_spawn.empty:
            cols_spawn = df_spawn.columns.tolist()
            col_spawn_id = next((c for c in cols_spawn if c in ['user_steamid', 'steamid', 'player_steamid', 'user_xuid']), None)

        if not col_atk:
            st.warning("IDs não encontrados.")
            return False

        # Limpeza
        for df in [df_death, df_blind, df_hurt, df_spawn]:
            if not df.empty and col_atk in df.columns: 
                df[col_atk] = df[col_atk].astype(str).str.replace(r'\.0$', '', regex=True)
            if not df.empty and col_vic in df.columns: 
                df[col_vic] = df[col_vic].astype(str).str.replace(r'\.0$', '', regex=True)
            if not df.empty and col_spawn_id and col_spawn_id in df.columns:
                df[col_spawn_id] = df[col_spawn_id].astype(str).str.replace(r'\.0$', '', regex=True)

        # LÓGICA DE JOGADORES
        for nome_exibicao, lista_ids in AMIGOS.items():
            lista_ids = [str(uid).strip() for uid in lista_ids]
            
            # Stats de Combate
            if not df_death.empty and col_atk in df_death.columns:
                meus_kills = df_death[df_death[col_atk].isin(lista_ids)]
                stats_partida[nome_exibicao]["Kills"] = len(meus_kills)
                if 'headshot' in meus_kills.columns:
                    stats_partida[nome_exibicao]["Headshots"] = len(meus_kills[meus_kills['headshot'] == True])
                if col_vic in df_death.columns:
                    stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic].isin(lista_ids)])

            if not df_blind.empty and col_atk in df_blind.columns:
                stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind[col_atk].isin(lista_ids)])
            
            if not df_hurt.empty and col_atk in df_hurt.columns and 'weapon' in df_hurt.columns:
                dmg = df_hurt[(df_hurt[col_atk].isin(lista_ids)) & (df_hurt['weapon'].isin(['hegrenade', 'inferno', 'incgrenade']))]
                stats_partida[nome_exibicao]["UtilityDamage"] = int(dmg['dmg_health'].sum())

            # CÁLCULO DE VITÓRIA HÍBRIDO (ROUND + MATCH PANEL)
            vitoria_confirmada = False
            
            # Método 1: Painel Final (O mais preciso, se existir)
            if not df_match_end.empty:
                # O evento cs_win_panel_match geralmente tem dados de quem ganhou
                # Mas é complexo de parsear ids individuais. Vamos usar como validador de rounds.
                pass 

            # Método 2: Round a Round com Spawn Check (Robusto)
            rounds_ganhos = 0
            total_rounds = 0
            
            if not df_round.empty:
                if not df_spawn.empty and col_spawn_id:
                    df_spawn_sorted = df_spawn.sort_values('tick')
                else: df_spawn_sorted = pd.DataFrame()

                for _, round_row in df_round.iterrows():
                    round_tick = round_row['tick']
                    winner_team = normalizar_time(round_row['winner'])
                    if not winner_team: continue 

                    # Descobre o time neste round
                    my_team = None
                    if not df_spawn_sorted.empty and col_spawn_id:
                        spawns = df_spawn_sorted[(df_spawn_sorted['tick'] <= round_tick) & (df_spawn_sorted[col_spawn_id].isin(lista_ids))]
                        if not spawns.empty:
                            last = spawns.iloc[-1]
                            if 'team_num' in last: my_team = normalizar_time(last['team_num'])
                            elif 'user_team_num' in last: my_team = normalizar_time(last['user_team_num'])
                    
                    if my_team == winner_team:
                        rounds_ganhos += 1
                    total_rounds += 1
            
            if total_rounds > 0 and rounds_ganhos > (total_rounds / 2):
                vitoria_confirmada = True

            if vitoria_confirmada:
                stats_partida[nome_exibicao]["Wins"] = 1
                
            if stats_partida[nome_exibicao]["Kills"] > 0 or stats_partida[nome_exibicao]["Deaths"] > 0:
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True

        if sucesso:
            atualizar_banco(stats_partida)
            registrar_demo(file_hash)

    except Exception as e:
        st.error(f"Erro: {e}")
    finally:
        os.remove(caminho_temp)
    return sucesso

# --- 3. INTERFACE ---
st.title("🔥 CS2 Pro Ranking")
tab1, tab2 = st.tabs(["📤 Upload", "🏆 Ranking"])

with tab1:
    arquivo = st.file_uploader("Arquivo .dem", type=["dem"])
    if arquivo and st.button("🚀 Processar Demo"):
        with st.spinner("Analisando com tecnologia LaihoE..."):
            if processar_demo(arquivo):
                st.success("Processado!")
                st.balloons()

with tab2:
    if st.button("🔄 Atualizar"): st.rerun()
    response = supabase.table('player_stats').select("*").execute()
    if response.data:
        df = pd.DataFrame(response.data)
        for c in ['kills', 'deaths', 'matches', 'wins', 'headshots', 'utility_damage', 'enemies_flashed']:
            if c not in df.columns: df[c] = 0
            
        df['KD'] = df.apply(lambda x: x['kills']/x['deaths'] if x['deaths']>0 else x['kills'], axis=1)
        df['Win%'] = df.apply(lambda x: (x['wins']/x['matches']*100) if x['matches']>0 else 0, axis=1)
        df['HS%'] = df.apply(lambda x: (x['headshots']/x['kills']*100) if x['kills']>0 else 0, axis=1)
        
        st.dataframe(
            df.sort_values(by='KD', ascending=False)[['nickname', 'KD', 'Win%', 'kills', 'deaths', 'HS%', 'enemies_flashed']],
            hide_index=True,
            column_config={"enemies_flashed": st.column_config.NumberColumn("Cegos 💡", format="%d")},
            use_container_width=True
        )
    else: st.info("Ranking vazio.")