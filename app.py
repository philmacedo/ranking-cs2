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

def ler_evento(parser, nome_evento):
    """Lê um evento da demo de forma simples e direta"""
    try:
        dados = parser.parse_events([nome_evento])
        if isinstance(dados, list) and len(dados) > 0:
            return pd.DataFrame(dados[0][1])
        return pd.DataFrame(dados)
    except Exception as e:
        st.warning(f"Aviso: Não consegui ler o evento '{nome_evento}': {e}")
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
        
        # 1. LEITURA DOS DADOS (Sem pedir colunas extras para evitar erro)
        df_round = ler_evento(parser, "round_end")
        df_spawn = ler_evento(parser, "player_spawn") 
        df_death = ler_evento(parser, "player_death")
        df_blind = ler_evento(parser, "player_blind")
        df_hurt = ler_evento(parser, "player_hurt")

        # Verifica se leu o básico
        if df_death.empty:
            st.error("Erro: Não encontrei dados de morte na demo.")
            return False

        # 2. IDENTIFICAÇÃO DE COLUNAS (Auto-detect)
        col_atk_id = next((c for c in df_death.columns if c in ['attacker_steamid', 'attacker_xuid', 'attacker_steamid64']), None)
        col_vic_id = next((c for c in df_death.columns if c in ['user_steamid', 'user_xuid', 'user_steamid64']), None)
        
        col_spawn_id = None
        if not df_spawn.empty:
            col_spawn_id = next((c for c in df_spawn.columns if c in ['user_steamid', 'steamid', 'userid_steamid']), None)

        if not col_atk_id:
            st.error("Erro: Colunas de SteamID não encontradas.")
            return False

        # 3. LIMPEZA DE IDS (Crucial)
        for df in [df_spawn, df_death, df_blind, df_hurt]:
            for col in df.columns:
                if 'steamid' in col or 'xuid' in col:
                    df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        # 4. MAPEAMENTO DE TIMES (Quem jogou onde?)
        # player_teams[steamid] = Lista de times que ele jogou [(tick, time)]
        player_teams = {}
        
        # Usa o SPAWN para saber o time (Mais confiável)
        if not df_spawn.empty:
            # Tenta achar a coluna de time
            col_team = next((c for c in df_spawn.columns if c in ['team_num', 'user_team_num']), None)
            
            if col_team:
                df_spawn = df_spawn.sort_values('tick')
                for _, row in df_spawn.iterrows():
                    uid = row.get(col_spawn_id)
                    team = normalizar_time(row.get(col_team))
                    if uid and team:
                        if uid not in player_teams: player_teams[uid] = []
                        player_teams[uid].append({'tick': row['tick'], 'team': team})
        
        # Fallback: Se o spawn falhou, tenta usar DEATH/KILL
        if not player_teams and not df_death.empty:
            st.warning("Aviso: Usando kills para detectar times (Spawn vazio ou sem time).")
            col_team_atk = next((c for c in df_death.columns if c in ['attacker_team_num', 'team_num']), None)
            if col_team_atk:
                for _, row in df_death.iterrows():
                    uid = row.get(col_atk_id)
                    team = normalizar_time(row.get(col_team_atk))
                    if uid and team:
                        if uid not in player_teams: player_teams[uid] = []
                        player_teams[uid].append({'tick': row['tick'], 'team': team})

        # 5. LISTA DE ROUNDS VÁLIDOS
        rounds_info = []
        if not df_round.empty and 'winner' in df_round.columns:
            for _, row in df_round.iterrows():
                w = normalizar_time(row['winner'])
                if w: rounds_info.append({'tick': row['tick'], 'winner': w})

        # --- PROCESSAMENTO POR JOGADOR ---
        for nome_exibicao, lista_ids in AMIGOS.items():
            lista_ids = [str(uid).strip() for uid in lista_ids]
            
            # COMBATE (Kills/Deaths)
            if not df_death.empty:
                my_kills = df_death[df_death[col_atk_id].isin(lista_ids)]
                stats_partida[nome_exibicao]["Kills"] = len(my_kills)
                
                if 'headshot' in my_kills.columns:
                    stats_partida[nome_exibicao]["Headshots"] = len(my_kills[my_kills['headshot']==True])
                
                if col_vic_id:
                    stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic_id].isin(lista_ids)])

            # UTILITIES (Flash/Dano)
            if not df_blind.empty:
                col_b_atk = next((c for c in df_blind.columns if 'attacker' in c), None)
                if col_b_atk:
                    stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind[col_b_atk].isin(lista_ids)])
            
            if not df_hurt.empty:
                col_h_atk = next((c for c in df_hurt.columns if 'attacker' in c), None)
                if col_h_atk and 'weapon' in df_hurt.columns:
                    dmg = df_hurt[(df_hurt[col_h_atk].isin(lista_ids)) & (df_hurt['weapon'].isin(['hegrenade', 'inferno', 'incgrenade']))]
                    stats_partida[nome_exibicao]["UtilityDamage"] = int(dmg['dmg_health'].sum())

            # CÁLCULO DE VITÓRIA (Round a Round)
            meus_pontos = 0
            total_rounds_validos = 0
            
            # Pega o histórico de times desse jogador
            meu_historico = []
            for uid in lista_ids:
                if uid in player_teams:
                    meu_historico = player_teams[uid]
                    break # Achou um ID com histórico, usa ele
            
            if rounds_info and meu_historico:
                for r in rounds_info:
                    r_tick = r['tick']
                    r_winner = r['winner']
                    
                    # Qual era meu time ANTES desse round acabar?
                    meu_time_no_round = None
                    # Filtra histórico anterior ao tick do round
                    passado = [h for h in meu_historico if h['tick'] < r_tick]
                    if passado:
                        meu_time_no_round = passado[-1]['team'] # O último registro antes do round acabar
                    
                    if meu_time_no_round == r_winner:
                        meus_pontos += 1
                    
                    total_rounds_validos += 1
            
            # Regra: Ganhou mais da metade dos rounds jogados?
            if total_rounds_validos > 0 and meus_pontos > (total_rounds_validos / 2):
                stats_partida[nome_exibicao]["Wins"] = 1

            # Participação
            if stats_partida[nome_exibicao]["Kills"] > 0 or stats_partida[nome_exibicao]["Deaths"] > 0:
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True

        if sucesso:
            atualizar_banco(stats_partida)
            registrar_demo(file_hash)
            return True
        else:
            st.warning("Nenhum jogador da lista foi encontrado com stats > 0.")
            return False

    except Exception as e:
        # ISSO VAI MOSTRAR O ERRO NA TELA
        st.error(f"Erro Fatal no Processamento: {e}")
        import traceback
        st.text(traceback.format_exc()) # Mostra detalhes técnicos
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