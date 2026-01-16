import streamlit as st
import pandas as pd
import os
import tempfile
import hashlib
import altair as alt
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

# --- 2. FUNÇÕES AUXILIARES ---

def normalizar_time(valor):
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

def criar_grafico_winrate(nome, win_rate, total_matches):
    """Cria um gráfico de rosca (Donut Chart) verde para o Win Rate"""
    cor = "#2ecc71" if win_rate >= 50 else "#e74c3c"
    
    source = pd.DataFrame({
        "Category": ["Vitórias", "Resto"],
        "Value": [win_rate, 100-win_rate]
    })
    
    base = alt.Chart(source).encode(theta=alt.Theta("Value", stack=True))
    pie = base.mark_arc(outerRadius=50, innerRadius=35).encode(
        color=alt.Color("Category", scale=alt.Scale(domain=["Vitórias", "Resto"], range=[cor, "#2c3e50"]), legend=None),
        order=alt.Order("Category", sort="descending")
    )
    text = base.mark_text(radius=0).encode(
        text=alt.value(f"{int(win_rate)}%"),
        color=alt.value("white"),
        size=alt.value(14)
    )
    return (pie + text).properties(title=f"{nome} ({total_matches} partidas)")

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
        df_team = ler_evento(parser, "player_team")

        # 2. COLUNAS ID (Específico para SteamID)
        col_atk_id = next((c for c in df_death.columns if c in ['attacker_steamid', 'attacker_xuid', 'attacker_steamid64']), None)
        col_vic_id = next((c for c in df_death.columns if c in ['user_steamid', 'user_xuid', 'user_steamid64']), None)
        col_team_id = next((c for c in df_team.columns if c in ['user_steamid', 'steamid', 'userid_steamid']), None)

        if not col_atk_id:
            st.error("Erro: IDs não encontrados.")
            return False

        # 3. LIMPEZA GERAL
        for df in [df_death, df_blind, df_hurt, df_team]:
            for col in df.columns:
                if 'steamid' in col or 'xuid' in col:
                    df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        # 4. TIMELINE DE TIMES (Lógica de Vitória)
        time_history = {}
        if not df_team.empty and col_team_id:
            df_team_sorted = df_team.sort_values('tick')
            for _, row in df_team_sorted.iterrows():
                uid = row[col_team_id]
                new_t = normalizar_time(row.get('team'))
                old_t = normalizar_time(row.get('oldteam'))
                if uid:
                    if uid not in time_history: 
                        time_history[uid] = []
                        if old_t: time_history[uid].append({'tick': 0, 'team': old_t})
                    if new_t: time_history[uid].append({'tick': row['tick'], 'team': new_t})

        # 5. ROUNDS
        rounds_data = []
        if not df_round.empty and 'winner' in df_round.columns:
            for _, row in df_round.iterrows():
                w = normalizar_time(row['winner'])
                if w: rounds_data.append({'tick': row['tick'], 'winner': w})

        # --- PROCESSAMENTO ---
        for nome_exibicao, lista_ids in AMIGOS.items():
            lista_ids = [str(uid).strip() for uid in lista_ids]
            
            # --- COMBATE (Kills/Deaths) ---
            if not df_death.empty and col_atk_id:
                my_kills = df_death[df_death[col_atk_id].isin(lista_ids)]
                stats_partida[nome_exibicao]["Kills"] = len(my_kills)
                if 'headshot' in my_kills.columns:
                    stats_partida[nome_exibicao]["Headshots"] = len(my_kills[my_kills['headshot']==True])
                if col_vic_id:
                    stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic_id].isin(lista_ids)])

            # --- CORREÇÃO: CEGOS (Flash) ---
            if not df_blind.empty:
                # Procura explicitamente coluna de ID, não apenas 'attacker'
                c_blind_id = next((c for c in df_blind.columns if c in ['attacker_steamid', 'attacker_xuid']), None)
                if c_blind_id:
                    # Garante limpeza do ID nesta tabela específica também
                    df_blind[c_blind_id] = df_blind[c_blind_id].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind[c_blind_id].isin(lista_ids)])
            
            # --- CORREÇÃO: DANO (Utility Damage) ---
            if not df_hurt.empty:
                # Procura explicitamente coluna de ID
                c_hurt_id = next((c for c in df_hurt.columns if c in ['attacker_steamid', 'attacker_xuid']), None)
                
                if c_hurt_id and 'weapon' in df_hurt.columns and 'dmg_health' in df_hurt.columns:
                    # Garante limpeza do ID
                    df_hurt[c_hurt_id] = df_hurt[c_hurt_id].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    
                    dmg = df_hurt[
                        (df_hurt[c_hurt_id].isin(lista_ids)) & 
                        (df_hurt['weapon'].isin(['hegrenade', 'inferno', 'incgrenade', 'molotov']))
                    ]
                    stats_partida[nome_exibicao]["UtilityDamage"] = int(dmg['dmg_health'].sum())

            # --- VITÓRIA (Timeline) ---
            meus_pontos = 0
            total_rounds = 0
            
            minha_timeline = []
            for uid in lista_ids:
                if uid in time_history:
                    minha_timeline = time_history[uid]
                    break
            
            if not minha_timeline and not df_death.empty:
                temp = []
                c_t = next((c for c in df_death.columns if 'attacker_team' in c or 'team_num' in c), None)
                if c_t:
                    ks = df_death[df_death[col_atk_id].isin(lista_ids)]
                    for _, r in ks.iterrows():
                        t = normalizar_time(r[c_t])
                        if t: temp.append({'tick': r['tick'], 'team': t})
                    if temp: minha_timeline = temp

            if rounds_data and minha_timeline:
                for r in rounds_data:
                    r_tick = r['tick']
                    r_winner = r['winner']
                    
                    meu_time = None
                    passado = [h for h in minha_timeline if h['tick'] <= r_tick]
                    if passado: meu_time = passado[-1]['team']
                    
                    if meu_time == r_winner: meus_pontos += 1
                    total_rounds += 1
            
            if total_rounds > 0 and meus_pontos > (total_rounds / 2):
                stats_partida[nome_exibicao]["Wins"] = 1

            # Participação (Se fez qualquer coisa, conta)
            if (stats_partida[nome_exibicao]["Kills"] > 0 or 
                stats_partida[nome_exibicao]["Deaths"] > 0 or
                stats_partida[nome_exibicao]["UtilityDamage"] > 0):
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True

        if sucesso:
            atualizar_banco(stats_partida)
            registrar_demo(file_hash)
            return True
        else:
            st.warning("Ninguém da lista jogou nesta partida.")
            return False

    except Exception as e:
        st.error(f"Erro: {e}")
        return False
    finally:
        if os.path.exists(caminho_temp): os.remove(caminho_temp)

# --- 3. INTERFACE ---
st.title("🔥 CS2 Pro Ranking")

tab1, tab2 = st.tabs(["📤 Upload", "🏆 Ranking"])

with tab1:
    arquivo = st.file_uploader("Arquivo .dem", type=["dem"])
    if arquivo and st.button("🚀 Processar"):
        with st.spinner("Analisando..."):
            if processar_demo(arquivo):
                st.success("Salvo!")
                st.balloons()

with tab2:
    if st.button("🔄 Atualizar"): st.rerun()
    
    response = supabase.table('player_stats').select("*").execute()
    if response.data:
        df = pd.DataFrame(response.data)
        cols = ['kills', 'deaths', 'matches', 'wins', 'headshots', 'utility_damage', 'enemies_flashed']
        for c in cols: 
            if c not in df.columns: df[c] = 0
            
        # Cálculos
        df['KD'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        df['WinRatePct'] = df.apply(lambda x: (x['wins'] / x['matches'] * 100) if x['matches'] > 0 else 0.0, axis=1)
        df['WinRateBar'] = df['WinRatePct'] / 100
        df['HS%'] = df.apply(lambda x: (x['headshots'] / x['kills'] * 100) if x['kills'] > 0 else 0.0, axis=1)
        df['Retrospecto'] = df.apply(lambda x: f"{int(x['wins'])} / {int(x['matches'])}", axis=1)
        
        df = df.sort_values(by='KD', ascending=False)
        
        # --- PARTE 1: GRÁFICOS ---
        st.subheader("🌟 Destaques (Win Rate)")
        top_players = df.head(4)
        cols = st.columns(4)
        for i, (index, row) in enumerate(top_players.iterrows()):
            with cols[i % 4]:
                chart = criar_grafico_winrate(row['nickname'], row['WinRatePct'], int(row['matches']))
                st.altair_chart(chart, use_container_width=True)

        st.divider()

        # --- PARTE 2: TABELA ---
        st.subheader("📋 Tabela Geral")
        st.dataframe(
            df[['nickname', 'KD', 'Retrospecto', 'WinRateBar', 'kills', 'deaths', 'HS%', 'enemies_flashed', 'utility_damage']],
            hide_index=True,
            column_config={
                "nickname": "Jogador",
                "KD": st.column_config.NumberColumn("K/D", format="%.2f ⭐"),
                "Retrospecto": st.column_config.TextColumn("Vitórias / Jogos"),
                "WinRateBar": st.column_config.ProgressColumn("Aproveitamento", format="%.0f%%", min_value=0, max_value=1),
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