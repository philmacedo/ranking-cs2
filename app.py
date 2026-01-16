import streamlit as st
import pandas as pd
import os
import tempfile
import hashlib
import altair as alt
from supabase import create_client, Client
from demoparser2 import DemoParser

# --- 1. CONFIGURAÇÃO E ESTILOS ---
st.set_page_config(page_title="CS2 Hub", page_icon="🔫", layout="wide")

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
    .rating-val { font-size: 36px; font-weight: bold; margin: 5px 0; color: #4CAF50; }
    .player-name { font-size: 20px; color: #FFF; margin-bottom: 5px; }
    .stat-row { font-size: 14px; color: #AAA; }
</style>
""", unsafe_allow_html=True)

try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
except FileNotFoundError:
    st.error("❌ Erro: Secrets não encontrados.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 2. LISTA DE AMIGOS (COM SMURFS) ---
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

# --- 3. FUNÇÕES AUXILIARES ---

def normalizar_time(valor):
    """Converte códigos de time para 2 (TR) ou 3 (CT)"""
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
                "kills": dados['Kills'], "deaths": dados['Deaths'], "assists": dados['Assists'],
                "matches": dados['Matches'], "wins": dados['Wins'], 
                "headshots": dados['Headshots'], "enemies_flashed": dados['EnemiesFlashed'], 
                "utility_damage": dados['UtilityDamage'], "total_damage": dados['TotalDamage'],
                "rounds_played": dados['RoundsPlayed']
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
    arquivo_bytes = arquivo_upload.read()
    file_hash = calcular_hash(arquivo_bytes)
    
    if demo_ja_processada(file_hash):
        st.error("⛔ Demo Duplicada! Esta partida já consta no Ranking Global.")
        return False, None

    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo_bytes)
    caminho_temp = tfile.name
    tfile.close()
    
    stats_partida = {nome: {"Kills": 0, "Deaths": 0, "Assists": 0, "Matches": 0, "Wins": 0, 
                            "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0, 
                            "TotalDamage": 0, "RoundsPlayed": 0} for nome in AMIGOS.keys()}
    sucesso = False
    
    try:
        parser = DemoParser(caminho_temp)
        
        # Leitura dos Eventos Cruciais
        df_round = ler_evento(parser, "round_end")
        df_death = ler_evento(parser, "player_death")
        df_blind = ler_evento(parser, "player_blind")
        df_hurt = ler_evento(parser, "player_hurt")
        df_team = ler_evento(parser, "player_team") # Trocas de time
        df_item = ler_evento(parser, "item_pickup") # Ajuda a rastrear time

        # Identificação de Colunas de ID
        col_atk_id = next((c for c in df_death.columns if c in ['attacker_steamid', 'attacker_xuid', 'attacker_steamid64']), None)
        col_vic_id = next((c for c in df_death.columns if c in ['user_steamid', 'user_xuid', 'user_steamid64']), None)
        col_ass_id = next((c for c in df_death.columns if c in ['assister_steamid', 'assister_xuid']), None)
        col_team_id = next((c for c in df_team.columns if c in ['user_steamid', 'steamid', 'userid_steamid']), None)
        col_item_id = next((c for c in df_item.columns if c in ['user_steamid', 'steamid']), None)

        if not col_atk_id: return False, None

        # Limpeza de IDs (remove .0)
        for df in [df_death, df_blind, df_hurt, df_team, df_item]:
            for col in df.columns:
                if 'steamid' in col or 'xuid' in col:
                    df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        # --- CONSTRUÇÃO DA TIMELINE (QUEM ERA O QUE E QUANDO?) ---
        time_history = {}
        
        # Função auxiliar para popular histórico
        def adicionar_historico(df_source, col_uid, col_team, col_oldteam=None):
            if not df_source.empty and col_uid and col_team in df_source.columns:
                df_sorted = df_source.sort_values('tick')
                for _, row in df_sorted.iterrows():
                    uid = row[col_uid]
                    new_t = normalizar_time(row.get(col_team))
                    if uid and new_t:
                        if uid not in time_history: 
                            time_history[uid] = []
                            # Se tiver oldteam, marca o início
                            if col_oldteam:
                                old_t = normalizar_time(row.get(col_oldteam))
                                if old_t: time_history[uid].append({'tick': 0, 'team': old_t})
                        time_history[uid].append({'tick': row['tick'], 'team': new_t})

        # 1. Fonte Primária: Evento de Troca de Time
        adicionar_historico(df_team, col_team_id, 'team', 'oldteam')
        
        # 2. Fonte Secundária: Item Pickup (Reforço)
        adicionar_historico(df_item, col_item_id, 'team_num')

        # 3. Fonte Terciária: Kills (Reforço)
        c_death_team = next((c for c in df_death.columns if c in ['attacker_team_num', 'team_num']), None)
        adicionar_historico(df_death, col_atk_id, c_death_team)

        # --- LISTA DE ROUNDS ---
        rounds_data = []
        if not df_round.empty and 'winner' in df_round.columns:
            for _, row in df_round.iterrows():
                w = normalizar_time(row['winner'])
                if w: rounds_data.append({'tick': row['tick'], 'winner': w})
        
        total_rounds_match = len(rounds_data)

        # --- PROCESSAMENTO POR JOGADOR ---
        for nome_exibicao, lista_ids in AMIGOS.items():
            lista_ids = [str(uid).strip() for uid in lista_ids]
            
            # 1. COMBATE
            if not df_death.empty and col_atk_id:
                my_kills = df_death[df_death[col_atk_id].isin(lista_ids)]
                stats_partida[nome_exibicao]["Kills"] = len(my_kills)
                
                if 'headshot' in my_kills.columns:
                    stats_partida[nome_exibicao]["Headshots"] = len(my_kills[my_kills['headshot']==True])
                if col_vic_id:
                    stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic_id].isin(lista_ids)])
                if col_ass_id:
                    stats_partida[nome_exibicao]["Assists"] = len(df_death[df_death[col_ass_id].isin(lista_ids)])

            # 2. FLASH (Busca ID específico)
            if not df_blind.empty:
                c_blind = next((c for c in df_blind.columns if c in ['attacker_steamid', 'attacker_xuid']), None)
                if c_blind:
                    df_blind[c_blind] = df_blind[c_blind].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind[c_blind].isin(lista_ids)])
            
            # 3. DANO (Busca ID específico)
            if not df_hurt.empty:
                c_hurt = next((c for c in df_hurt.columns if c in ['attacker_steamid', 'attacker_xuid']), None)
                if c_hurt and 'dmg_health' in df_hurt.columns:
                    df_hurt[c_hurt] = df_hurt[c_hurt].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    
                    meu_dano = df_hurt[df_hurt[c_hurt].isin(lista_ids)]
                    stats_partida[nome_exibicao]["TotalDamage"] = int(meu_dano['dmg_health'].sum())
                    
                    if 'weapon' in df_hurt.columns:
                        dmg_util = meu_dano[meu_dano['weapon'].isin(['hegrenade', 'inferno', 'incgrenade', 'molotov'])]
                        stats_partida[nome_exibicao]["UtilityDamage"] = int(dmg_util['dmg_health'].sum())

            # 4. VITÓRIA (Consulta a Timeline Unificada)
            meus_pontos = 0
            total_rounds_jogados = 0 
            
            # Junta as timelines de todos os IDs (Main + Smurfs)
            minha_timeline = []
            for uid in lista_ids:
                if uid in time_history:
                    minha_timeline.extend(time_history[uid])
            minha_timeline.sort(key=lambda x: x['tick'])

            if rounds_data and minha_timeline:
                for r in rounds_data:
                    r_tick = r['tick']
                    r_winner = r['winner']
                    meu_time = None
                    passado = [h for h in minha_timeline if h['tick'] <= r_tick]
                    if passado: meu_time = passado[-1]['team']
                    
                    if meu_time:
                        total_rounds_jogados += 1
                        if meu_time == r_winner: meus_pontos += 1
            
            # Se a timeline falhou, assume que jogou tudo
            if total_rounds_jogados == 0: total_rounds_jogados = total_rounds_match
            stats_partida[nome_exibicao]["RoundsPlayed"] = total_rounds_jogados

            if total_rounds_jogados > 0 and meus_pontos > (total_rounds_jogados / 2):
                stats_partida[nome_exibicao]["Wins"] = 1

            # Participação
            if (stats_partida[nome_exibicao]["Kills"] > 0 or 
                stats_partida[nome_exibicao]["Deaths"] > 0 or 
                stats_partida[nome_exibicao]["UtilityDamage"] > 0):
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True

        if sucesso:
            atualizar_banco(stats_partida)
            registrar_demo(file_hash)
            
            # Prepara dados para exibir
            rows = []
            for k, v in stats_partida.items():
                if v['Matches'] > 0:
                    rows.append({
                        "nickname": k,
                        "kills": v['Kills'], "deaths": v['Deaths'], "assists": v['Assists'],
                        "wins": v['Wins'], "headshots": v['Headshots'], 
                        "enemies_flashed": v['EnemiesFlashed'], "utility_damage": v['UtilityDamage'],
                        "total_damage": v['TotalDamage'], "rounds_played": v['RoundsPlayed'],
                        "matches": v['Matches']
                    })
            return True, pd.DataFrame(rows)
        else:
            return False, None

    except Exception as e:
        st.error(f"Erro Fatal: {e}")
        return False, None
    finally:
        if os.path.exists(caminho_temp): os.remove(caminho_temp)

# --- 4. INTERFACE E NAVEGAÇÃO ---
st.sidebar.title("Navegação")
pagina = st.sidebar.radio("Ir para:", ["📤 Upload & Partida Atual", "🏆 Ranking Global"], label_visibility="collapsed")

# === PÁGINA 1: UPLOAD ===
if pagina == "📤 Upload & Partida Atual":
    st.title("📤 Upload de Demo")
    st.markdown("Suba o arquivo `.dem` para analisar a partida e enviá-la ao Ranking.")
    
    arquivo = st.file_uploader("Arraste o arquivo aqui", type=["dem"])
    if "df_partida_atual" not in st.session_state: st.session_state["df_partida_atual"] = None

    if arquivo:
        if st.button("🚀 Processar Partida"):
            with st.spinner("Analisando cada tick da demo..."):
                sucesso, df_resultado = processar_demo(arquivo)
                if sucesso:
                    st.success("✅ Partida salva e processada!")
                    st.session_state["df_partida_atual"] = df_resultado
                    st.balloons()
    
    if st.session_state["df_partida_atual"] is not None:
        st.divider()
        st.subheader("📊 Relatório da Partida Atual")
        df = st.session_state["df_partida_atual"].copy()
        
        # Cálculos desta partida
        df['KD'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        df['ADR'] = df.apply(lambda x: x['total_damage'] / x['rounds_played'] if x['rounds_played'] > 0 else 0, axis=1)
        df['Rating'] = df.apply(lambda x: (x['kills'] + (x['assists']*0.4) + (x['enemies_flashed']*0.2) + (x['utility_damage']*0.01)) / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        df['Resultado'] = df['wins'].apply(lambda x: "🏆 Vitória" if x == 1 else "💀 Derrota")
        
        df = df.sort_values(by='Rating', ascending=False)
        
        st.dataframe(
            df[['nickname', 'Resultado', 'Rating', 'KD', 'ADR', 'kills', 'assists', 'deaths', 'enemies_flashed', 'utility_damage']],
            hide_index=True,
            column_config={
                "nickname": "Jogador", "Rating": st.column_config.NumberColumn("RATING", format="%.2f ⭐"),
                "KD": st.column_config.NumberColumn("K/D", format="%.2f"), "ADR": st.column_config.NumberColumn("ADR", format="%.1f"),
                "kills": "K", "deaths": "D", "assists": "A", "enemies_flashed": "Cegos", "utility_damage": "Util Dmg"
            },
            use_container_width=True
        )

# === PÁGINA 2: RANKING GLOBAL ===
elif pagina == "🏆 Ranking Global":
    st.title("🏆 Ranking Global")
    
    col_top1, col_top2 = st.columns([3, 1])
    with col_top1:
        st.info("ℹ️ **Fator de Consistência:** Jogadores com menos de 5 partidas têm penalidade no Rating.")
    with col_top2:
        if st.button("🔄 Atualizar Dados"): st.rerun()
    
    # 1. Dados do Banco
    response = supabase.table('player_stats').select("*").execute()
    db_data = pd.DataFrame(response.data) if response.data else pd.DataFrame()
    
    # 2. Merge com TODOS os amigos (para mostrar quem tem 0)
    all_friends = pd.DataFrame({"nickname": list(AMIGOS.keys())})
    if not db_data.empty:
        df = pd.merge(all_friends, db_data, on="nickname", how="left")
    else:
        df = all_friends
        
    # 3. Zeros
    cols_stats = ['kills', 'deaths', 'assists', 'matches', 'wins', 'headshots', 
                  'enemies_flashed', 'utility_damage', 'total_damage', 'rounds_played']
    for c in cols_stats:
        if c not in df.columns: df[c] = 0
    df[cols_stats] = df[cols_stats].fillna(0)

    # 4. Cálculos
    df['KD'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
    df['WinRatePct'] = df.apply(lambda x: (x['wins'] / x['matches'] * 100) if x['matches'] > 0 else 0.0, axis=1)
    df['ADR'] = df.apply(lambda x: x['total_damage'] / x['rounds_played'] if x['rounds_played'] > 0 else 0, axis=1)
    df['Retrospecto'] = df.apply(lambda x: f"{int(x['wins'])} / {int(x['matches'])}", axis=1)
    
    # Rating Raw
    df['RatingRaw'] = df.apply(lambda x: (x['kills'] + (x['assists']*0.4) + (x['enemies_flashed']*0.2) + (x['utility_damage']*0.01)) / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
    
    # Rating Final (Consistência)
    META_PARTIDAS = 5
    df['Consistency'] = df['matches'].apply(lambda x: x / META_PARTIDAS if x < META_PARTIDAS else 1.0)
    df['RatingFinal'] = df['RatingRaw'] * df['Consistency']

    # 5. Filtros
    with st.expander("🔍 Filtros", expanded=False):
        sel_players = st.multiselect("Filtrar Jogadores", options=df['nickname'].unique())
        min_matches = st.slider("Mínimo de Partidas", 0, 20, 0)
    
    df_display = df[df['matches'] >= min_matches].copy()
    if sel_players:
        df_display = df_display[df_display['nickname'].isin(sel_players)]

    # Ordenação
    df_podium = df_display.sort_values(by='RatingFinal', ascending=False).reset_index(drop=True)
    
    # --- PÓDIO ---
    if len(df_podium) >= 3 and df_podium.iloc[0]['RatingFinal'] > 0:
        col1, col2, col3 = st.columns([1, 1.2, 1])
        
        with col1: # Prata
            p2 = df_podium.iloc[1]
            st.markdown(f"""
            <div class="podium-card silver">
                <div style="font-size:40px;">🥈</div>
                <div class="player-name">{p2['nickname']}</div>
                <div class="rating-val">{p2['RatingFinal']:.2f}</div>
                <div class="stat-row">Rating Ajustado</div>
                <div style="color:#aaa;">{int(p2['matches'])} partidas</div>
            </div>""", unsafe_allow_html=True)
            
        with col2: # Ouro
            p1 = df_podium.iloc[0]
            st.markdown(f"""
            <div class="podium-card gold">
                <div style="font-size:60px;">👑</div>
                <div class="player-name" style="color:#FFD700;">{p1['nickname']}</div>
                <div class="rating-val" style="color:#FFD700; font-size:48px;">{p1['RatingFinal']:.2f}</div>
                <div class="stat-row" style="color:#FFD700;">Rating Ajustado</div>
                <div style="color:#DDD;">{int(p1['matches'])} partidas</div>
            </div>""", unsafe_allow_html=True)

        with col3: # Bronze
            p3 = df_podium.iloc[2]
            st.markdown(f"""
            <div class="podium-card bronze">
                <div style="font-size:40px;">🥉</div>
                <div class="player-name">{p3['nickname']}</div>
                <div class="rating-val">{p3['RatingFinal']:.2f}</div>
                <div class="stat-row">Rating Ajustado</div>
                <div style="color:#cd7f32;">{int(p3['matches'])} partidas</div>
            </div>""", unsafe_allow_html=True)
    
    st.divider()
    
    # --- TABELA ---
    st.subheader("📋 Classificação Oficial")
    st.dataframe(
        df_podium[['nickname', 'RatingFinal', 'RatingRaw', 'Retrospecto', 'KD', 'ADR', 'WinRatePct', 'kills', 'deaths', 'enemies_flashed', 'utility_damage']],
        hide_index=True,
        column_config={
            "nickname": "Jogador",
            "RatingFinal": st.column_config.NumberColumn("RATING OFICIAL", format="%.2f ⭐", help="Com penalidade de consistência"),
            "RatingRaw": st.column_config.NumberColumn("Rating Real", format="%.2f", help="Performance pura"),
            "Retrospecto": "Vit/Jogos",
            "KD": st.column_config.NumberColumn("K/D", format="%.2f"),
            "ADR": st.column_config.NumberColumn("ADR", format="%.1f"),
            "WinRatePct": st.column_config.NumberColumn("Win%", format="%.0f%%"),
            "kills": "K", "deaths": "D", "enemies_flashed": "Cegos", "utility_damage": "Util Dmg"
        },
        use_container_width=True
    )

    # --- EXPLICAÇÃO ---
    st.divider()
    with st.expander("ℹ️ Como funciona o cálculo?"):
        st.markdown(r"""
        ### 1. Rating Performance (A Nota)
        $$
        \text{Rating} = \frac{\text{Kills} + (\text{Assists} \times 0.4) + (\text{Cegos} \times 0.2) + (\text{DanoUtil} \div 100)}{\text{Mortes}}
        $$
        
        ### 2. Consistência
        Se jogar menos de 5 partidas, o Rating é penalizado proporcionalmente.
        """)
