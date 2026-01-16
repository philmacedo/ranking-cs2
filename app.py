import streamlit as st
import pandas as pd
import os
import tempfile
import hashlib
import altair as alt
from supabase import create_client, Client
from demoparser2 import DemoParser

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="CS2 Hub", page_icon="🔫", layout="wide")

# CSS para o Pódio e Cartões
st.markdown("""
<style>
    .podium-card {
        background-color: #1E1E1E;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
        border: 2px solid #333;
        transition: transform 0.3s;
    }
    .podium-card:hover { transform: scale(1.05); }
    .gold { border-color: #FFD700; box-shadow: 0 0 15px rgba(255, 215, 0, 0.3); }
    .silver { border-color: #C0C0C0; box-shadow: 0 0 10px rgba(192, 192, 192, 0.3); }
    .bronze { border-color: #CD7F32; box-shadow: 0 0 10px rgba(205, 127, 50, 0.3); }
    .big-stat { font-size: 24px; font-weight: bold; margin: 10px 0; }
    .player-name { font-size: 20px; color: #FFF; margin-bottom: 5px; }
</style>
""", unsafe_allow_html=True)

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

def atualizar_banco(stats_novos):
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

def processar_demo(arquivo_upload):
    # Retorna (Sucesso: bool, DataFrame_da_Partida: pd.DataFrame)
    arquivo_bytes = arquivo_upload.read()
    file_hash = calcular_hash(arquivo_bytes)
    
    if demo_ja_processada(file_hash):
        st.error("⛔ Demo Duplicada! Esta partida já foi contabilizada no Ranking Global.")
        return False, None

    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo_bytes)
    caminho_temp = tfile.name
    tfile.close()
    
    stats_partida = {nome: {"Kills": 0, "Deaths": 0, "Matches": 0, "Wins": 0, "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0} for nome in AMIGOS.keys()}
    sucesso = False
    
    try:
        parser = DemoParser(caminho_temp)
        
        # Leitura
        df_round = ler_evento(parser, "round_end")
        df_death = ler_evento(parser, "player_death")
        df_blind = ler_evento(parser, "player_blind")
        df_hurt = ler_evento(parser, "player_hurt")
        df_team = ler_evento(parser, "player_team")

        # Colunas ID
        col_atk_id = next((c for c in df_death.columns if c in ['attacker_steamid', 'attacker_xuid', 'attacker_steamid64']), None)
        col_vic_id = next((c for c in df_death.columns if c in ['user_steamid', 'user_xuid', 'user_steamid64']), None)
        col_team_id = next((c for c in df_team.columns if c in ['user_steamid', 'steamid', 'userid_steamid']), None)

        if not col_atk_id:
            return False, None

        # Limpeza
        for df in [df_death, df_blind, df_hurt, df_team]:
            for col in df.columns:
                if 'steamid' in col or 'xuid' in col:
                    df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        # Timeline
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

        # Rounds
        rounds_data = []
        if not df_round.empty and 'winner' in df_round.columns:
            for _, row in df_round.iterrows():
                w = normalizar_time(row['winner'])
                if w: rounds_data.append({'tick': row['tick'], 'winner': w})

        # Processamento
        for nome_exibicao, lista_ids in AMIGOS.items():
            lista_ids = [str(uid).strip() for uid in lista_ids]
            
            # Combate
            if not df_death.empty and col_atk_id:
                my_kills = df_death[df_death[col_atk_id].isin(lista_ids)]
                stats_partida[nome_exibicao]["Kills"] = len(my_kills)
                if 'headshot' in my_kills.columns:
                    stats_partida[nome_exibicao]["Headshots"] = len(my_kills[my_kills['headshot']==True])
                if col_vic_id:
                    stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic_id].isin(lista_ids)])

            # Flash
            if not df_blind.empty:
                c_blind_id = next((c for c in df_blind.columns if c in ['attacker_steamid', 'attacker_xuid']), None)
                if c_blind_id:
                    df_blind[c_blind_id] = df_blind[c_blind_id].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind[c_blind_id].isin(lista_ids)])
            
            # Dano
            if not df_hurt.empty:
                c_hurt_id = next((c for c in df_hurt.columns if c in ['attacker_steamid', 'attacker_xuid']), None)
                if c_hurt_id and 'weapon' in df_hurt.columns and 'dmg_health' in df_hurt.columns:
                    df_hurt[c_hurt_id] = df_hurt[c_hurt_id].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    dmg = df_hurt[(df_hurt[c_hurt_id].isin(lista_ids)) & (df_hurt['weapon'].isin(['hegrenade', 'inferno', 'incgrenade', 'molotov']))]
                    stats_partida[nome_exibicao]["UtilityDamage"] = int(dmg['dmg_health'].sum())

            # Vitória
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

            if (stats_partida[nome_exibicao]["Kills"] > 0 or stats_partida[nome_exibicao]["Deaths"] > 0 or stats_partida[nome_exibicao]["UtilityDamage"] > 0):
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True

        if sucesso:
            atualizar_banco(stats_partida)
            registrar_demo(file_hash)
            
            # Cria DataFrame para exibir na página 1
            rows = []
            for k, v in stats_partida.items():
                if v['Matches'] > 0:
                    rows.append({
                        "nickname": k,
                        "kills": v['Kills'], "deaths": v['Deaths'], "wins": v['Wins'],
                        "headshots": v['Headshots'], "enemies_flashed": v['EnemiesFlashed'],
                        "utility_damage": v['UtilityDamage'], "matches": v['Matches']
                    })
            return True, pd.DataFrame(rows)
        else:
            return False, None

    except Exception as e:
        st.error(f"Erro: {e}")
        return False, None
    finally:
        if os.path.exists(caminho_temp): os.remove(caminho_temp)

# --- 3. NAVEGAÇÃO ---
# Menu Lateral
st.sidebar.title("Menu")
pagina = st.sidebar.radio("Navegar", ["📤 Upload & Partida Atual", "🏆 Ranking Global"], label_visibility="collapsed")

# --- PÁGINA 1: UPLOAD E DADOS DA PARTIDA ---
if pagina == "📤 Upload & Partida Atual":
    st.title("📤 Upload de Demo")
    st.write("Suba o arquivo `.dem` para processar a partida e ver os dados **deste jogo**.")
    
    arquivo = st.file_uploader("Arquivo .dem", type=["dem"])
    
    if "df_partida_atual" not in st.session_state:
        st.session_state["df_partida_atual"] = None

    if arquivo:
        if st.button("🚀 Processar Partida"):
            with st.spinner("Analisando timeline e stats..."):
                sucesso, df_resultado = processar_demo(arquivo)
                if sucesso:
                    st.success("✅ Partida processada e adicionada ao Ranking Global!")
                    st.session_state["df_partida_atual"] = df_resultado
                    st.balloons()
    
    # Exibe dados da partida atual (se houver)
    if st.session_state["df_partida_atual"] is not None:
        st.divider()
        st.subheader("📊 Relatório da Partida")
        
        df = st.session_state["df_partida_atual"].copy()
        
        # Cálculos específicos da partida
        df['KD'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        df['HS%'] = df.apply(lambda x: (x['headshots'] / x['kills'] * 100) if x['kills'] > 0 else 0.0, axis=1)
        df['Resultado'] = df['wins'].apply(lambda x: "🏆 Vitória" if x == 1 else "💀 Derrota")
        
        df = df.sort_values(by='KD', ascending=False)
        
        st.dataframe(
            df[['nickname', 'Resultado', 'KD', 'kills', 'deaths', 'HS%', 'enemies_flashed', 'utility_damage']],
            hide_index=True,
            column_config={
                "nickname": "Jogador",
                "KD": st.column_config.NumberColumn("K/D", format="%.2f"),
                "HS%": st.column_config.NumberColumn("HS %", format="%.1f%%"),
                "enemies_flashed": "Cegos 💡",
                "utility_damage": "Dano Util 💣",
                "kills": "K", "deaths": "D"
            },
            use_container_width=True
        )

# --- PÁGINA 2: RANKING GLOBAL (PÓDIO) ---
elif pagina == "🏆 Ranking Global":
    st.title("🏆 Ranking Global")
    
    if st.button("🔄 Atualizar Dados"): st.rerun()
    
    response = supabase.table('player_stats').select("*").execute()
    
    if response.data:
        df = pd.DataFrame(response.data)
        cols = ['kills', 'deaths', 'matches', 'wins', 'headshots', 'utility_damage', 'enemies_flashed']
        for c in cols: 
            if c not in df.columns: df[c] = 0
            
        # Cálculos Globais
        df['KD'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        df['WinRatePct'] = df.apply(lambda x: (x['wins'] / x['matches'] * 100) if x['matches'] > 0 else 0.0, axis=1)
        df['HS%'] = df.apply(lambda x: (x['headshots'] / x['kills'] * 100) if x['kills'] > 0 else 0.0, axis=1)
        df['Retrospecto'] = df.apply(lambda x: f"{int(x['wins'])} / {int(x['matches'])}", axis=1)
        
        # Ordena por KD para o pódio (pode mudar para WinRate se preferir)
        df_podium = df.sort_values(by='KD', ascending=False).reset_index(drop=True)
        
        # --- ANIMAÇÃO DO PÓDIO ---
        if len(df_podium) >= 3:
            col1, col2, col3 = st.columns([1, 1.2, 1]) # O do meio é maior (1o lugar)
            
            # 2º Lugar (Prata) - Esquerda
            with col1:
                p2 = df_podium.iloc[1]
                st.markdown(f"""
                <div class="podium-card silver">
                    <div style="font-size:40px;">🥈</div>
                    <div class="player-name">{p2['nickname']}</div>
                    <div class="big-stat">{p2['KD']:.2f} KD</div>
                    <div style="color:#aaa;">{int(p2['WinRatePct'])}% Win Rate</div>
                </div>
                """, unsafe_allow_html=True)
                
            # 1º Lugar (Ouro) - Centro
            with col2:
                p1 = df_podium.iloc[0]
                st.markdown(f"""
                <div class="podium-card gold">
                    <div style="font-size:60px;">👑</div>
                    <div class="player-name" style="font-size:26px; color:#FFD700;">{p1['nickname']}</div>
                    <div class="big-stat" style="font-size:32px;">{p1['KD']:.2f} KD</div>
                    <div style="color:#FFD700;">{int(p1['WinRatePct'])}% Win Rate</div>
                    <br>
                </div>
                """, unsafe_allow_html=True)
                if st.button("🎉 Celebrar Líder"): st.balloons()

            # 3º Lugar (Bronze) - Direita
            with col3:
                p3 = df_podium.iloc[2]
                st.markdown(f"""
                <div class="podium-card bronze">
                    <div style="font-size:40px;">🥉</div>
                    <div class="player-name">{p3['nickname']}</div>
                    <div class="big-stat">{p3['KD']:.2f} KD</div>
                    <div style="color:#cd7f32;">{int(p3['WinRatePct'])}% Win Rate</div>
                </div>
                """, unsafe_allow_html=True)
        
        st.divider()
        
        # --- TABELA GERAL ---
        st.subheader("📋 Classificação Completa")
        st.dataframe(
            df_podium[['nickname', 'KD', 'Retrospecto', 'WinRatePct', 'kills', 'deaths', 'HS%', 'enemies_flashed', 'utility_damage']],
            hide_index=True,
            column_config={
                "nickname": "Jogador",
                "KD": st.column_config.NumberColumn("K/D", format="%.2f ⭐"),
                "Retrospecto": st.column_config.TextColumn("Vitórias / Jogos", help="Total de Vitórias"),
                "WinRatePct": st.column_config.NumberColumn("Aprov.", format="%.0f%%"),
                "HS%": st.column_config.NumberColumn("HS %", format="%.1f%% 🎯"),
                "enemies_flashed": st.column_config.NumberColumn("Cegos 💡"),
                "utility_damage": st.column_config.NumberColumn("Dano Util 💣"),
                "kills": "Kills",
                "deaths": "Mortes"
            },
            use_container_width=True
        )
    else:
        st.info("O Ranking Global ainda está vazio. Suba a primeira demo!")
