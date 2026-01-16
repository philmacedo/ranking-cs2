import streamlit as st
import pandas as pd
import os
import tempfile
import hashlib
import altair as alt
import plotly.graph_objects as go
from supabase import create_client, Client
from demoparser2 import DemoParser

# --- 1. CONFIGURAÇÃO E ESTILOS (TEMA CS2) ---
st.set_page_config(page_title=" Jogatina CS2 Ranking", page_icon="🔫", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0e1012; }
    .podium-card {
        background-color: #1c222b;
        border-radius: 8px;
        padding: 20px;
        text-align: center;
        border: 1px solid #2d3542;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        transition: transform 0.2s;
    }
    .podium-card:hover { transform: translateY(-5px); border-color: #e9a338; }
    .gold { border-top: 4px solid #FFD700; }
    .silver { border-top: 4px solid #C0C0C0; }
    .bronze { border-top: 4px solid #CD7F32; }
    .rating-val { font-family: 'Inter', sans-serif; font-size: 42px; font-weight: 800; margin: 10px 0; color: #e9a338; }
    .player-name { font-size: 22px; font-weight: 600; color: #f1f1f1; margin-bottom: 5px; text-transform: uppercase; }
    .stat-row { font-size: 14px; color: #8b9bb4; font-weight: 500; }
    h1, h2, h3 { color: #f1f1f1 !important; }
    p, span, li { color: #cfdae6; }
</style>
""", unsafe_allow_html=True)

try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
except FileNotFoundError:
    st.error("❌ Erro: Secrets não encontrados.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 2. LISTA DE AMIGOS ---
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

def arquivar_e_resetar(nome_temporada):
    """Copia dados atuais para o histórico e limpa as tabelas principais"""
    try:
        # 1. Busca dados atuais
        stats_atuais = supabase.table('player_stats').select("*").execute().data
        mapas_atuais = supabase.table('player_map_stats').select("*").execute().data
        
        # 2. Prepara para Histórico (Adiciona nome da season e remove ID original)
        if stats_atuais:
            for row in stats_atuais:
                row['season_name'] = nome_temporada
                if 'id' in row: del row['id']
                if 'created_at' in row: del row['created_at']
            supabase.table('history_player_stats').insert(stats_atuais).execute()

        if mapas_atuais:
            for row in mapas_atuais:
                row['season_name'] = nome_temporada
                if 'id' in row: del row['id']
            supabase.table('history_map_stats').insert(mapas_atuais).execute()

        # 3. Limpa tabelas principais
        supabase.table('player_stats').delete().gte('matches', 0).execute()
        try: supabase.table('player_map_stats').delete().gte('matches', 0).execute() 
        except: pass
        supabase.table('processed_matches').delete().neq('match_hash', '0').execute()
        
        return True
    except Exception as e:
        st.error(f"Erro ao arquivar: {e}")
        return False

def atualizar_banco(stats_novos, mapa_atual):
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
            except Exception as e: st.error(f"Erro BD (Geral): {e}")

            if mapa_atual:
                try:
                    resp_map = supabase.table('player_map_stats').select("*").eq('nickname', nick).eq('map_name', mapa_atual).execute()
                    if resp_map.data:
                        atual_map = resp_map.data[0]
                        supabase.table('player_map_stats').update({
                            "matches": atual_map['matches'] + 1,
                            "wins": atual_map['wins'] + (1 if dados['Wins'] > 0 else 0)
                        }).eq('id', atual_map['id']).execute()
                    else:
                        supabase.table('player_map_stats').insert({
                            "nickname": nick, "map_name": mapa_atual,
                            "matches": 1, "wins": 1 if dados['Wins'] > 0 else 0
                        }).execute()
                except: pass

def processar_demo(arquivo_upload):
    arquivo_bytes = arquivo_upload.read()
    file_hash = calcular_hash(arquivo_bytes)
    
    if demo_ja_processada(file_hash):
        st.error("⛔ Demo Duplicada!")
        return False, None

    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo_bytes)
    caminho_temp = tfile.name
    tfile.close()
    
    stats_partida = {nome: {"Kills": 0, "Deaths": 0, "Assists": 0, "Matches": 0, "Wins": 0, 
                            "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0, 
                            "TotalDamage": 0, "RoundsPlayed": 0} for nome in AMIGOS.keys()}
    sucesso = False
    mapa_nome = "Desconhecido"

    try:
        parser = DemoParser(caminho_temp)
        try:
            header = parser.parse_header()
            if "map_name" in header: mapa_nome = header["map_name"].replace("de_", "").capitalize()
        except: pass

        df_round = ler_evento(parser, "round_end")
        df_death = ler_evento(parser, "player_death")
        df_blind = ler_evento(parser, "player_blind")
        df_hurt = ler_evento(parser, "player_hurt")
        df_team = ler_evento(parser, "player_team")
        df_item = ler_evento(parser, "item_pickup")

        col_atk_id = next((c for c in df_death.columns if c in ['attacker_steamid', 'attacker_xuid']), None)
        col_vic_id = next((c for c in df_death.columns if c in ['user_steamid', 'user_xuid']), None)
        col_ass_id = next((c for c in df_death.columns if c in ['assister_steamid', 'assister_xuid']), None)
        col_team_id = next((c for c in df_team.columns if c in ['user_steamid', 'steamid']), None)
        col_item_id = next((c for c in df_item.columns if c in ['user_steamid', 'steamid']), None)

        if not col_atk_id: return False, None

        for df in [df_death, df_blind, df_hurt, df_team, df_item]:
            for col in df.columns:
                if 'steamid' in col or 'xuid' in col:
                    df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        time_history = {}
        def adicionar_historico(df_source, col_uid, col_team, col_oldteam=None):
            if not df_source.empty and col_uid and col_team in df_source.columns:
                df_sorted = df_source.sort_values('tick')
                for _, row in df_sorted.iterrows():
                    uid = row[col_uid]
                    new_t = normalizar_time(row.get(col_team))
                    if uid and new_t:
                        if uid not in time_history: 
                            time_history[uid] = []
                            if col_oldteam:
                                old_t = normalizar_time(row.get(col_oldteam))
                                if old_t: time_history[uid].append({'tick': 0, 'team': old_t})
                        time_history[uid].append({'tick': row['tick'], 'team': new_t})

        adicionar_historico(df_team, col_team_id, 'team', 'oldteam')
        adicionar_historico(df_item, col_item_id, 'team_num')
        c_death_team = next((c for c in df_death.columns if c in ['attacker_team_num', 'team_num']), None)
        adicionar_historico(df_death, col_atk_id, c_death_team)

        rounds_data = []
        if not df_round.empty and 'winner' in df_round.columns:
            for _, row in df_round.iterrows():
                w = normalizar_time(row['winner'])
                if w: rounds_data.append({'tick': row['tick'], 'winner': w})
        total_rounds_match = len(rounds_data)

        for nome_exibicao, lista_ids in AMIGOS.items():
            lista_ids = [str(uid).strip() for uid in lista_ids]
            if not df_death.empty and col_atk_id:
                my_kills = df_death[df_death[col_atk_id].isin(lista_ids)]
                stats_partida[nome_exibicao]["Kills"] = len(my_kills)
                if 'headshot' in my_kills.columns: stats_partida[nome_exibicao]["Headshots"] = len(my_kills[my_kills['headshot']==True])
                if col_vic_id: stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic_id].isin(lista_ids)])
                if col_ass_id: stats_partida[nome_exibicao]["Assists"] = len(df_death[df_death[col_ass_id].isin(lista_ids)])

            if not df_blind.empty:
                c_blind = next((c for c in df_blind.columns if c in ['attacker_steamid', 'attacker_xuid']), None)
                if c_blind:
                    df_blind[c_blind] = df_blind[c_blind].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind[c_blind].isin(lista_ids)])
            
            if not df_hurt.empty:
                c_hurt = next((c for c in df_hurt.columns if c in ['attacker_steamid', 'attacker_xuid']), None)
                if c_hurt and 'dmg_health' in df_hurt.columns:
                    df_hurt[c_hurt] = df_hurt[c_hurt].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    meu_dano = df_hurt[df_hurt[c_hurt].isin(lista_ids)]
                    stats_partida[nome_exibicao]["TotalDamage"] = int(meu_dano['dmg_health'].sum())
                    if 'weapon' in df_hurt.columns:
                        dmg_util = meu_dano[meu_dano['weapon'].isin(['hegrenade', 'inferno', 'incgrenade', 'molotov'])]
                        stats_partida[nome_exibicao]["UtilityDamage"] = int(dmg_util['dmg_health'].sum())

            meus_pontos = 0
            total_rounds_jogados = 0 
            minha_timeline = []
            for uid in lista_ids:
                if uid in time_history: minha_timeline.extend(time_history[uid])
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
            
            if total_rounds_jogados == 0: total_rounds_jogados = total_rounds_match
            stats_partida[nome_exibicao]["RoundsPlayed"] = total_rounds_jogados

            if total_rounds_jogados > 0 and meus_pontos > (total_rounds_jogados / 2):
                stats_partida[nome_exibicao]["Wins"] = 1

            if (stats_partida[nome_exibicao]["Kills"] > 0 or stats_partida[nome_exibicao]["Deaths"] > 0 or stats_partida[nome_exibicao]["UtilityDamage"] > 0):
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True

        if sucesso:
            atualizar_banco(stats_partida, mapa_nome)
            registrar_demo(file_hash)
            rows = []
            for k, v in stats_partida.items():
                if v['Matches'] > 0:
                    rows.append({
                        "nickname": k, "mapa": mapa_nome, "kills": v['Kills'], "deaths": v['Deaths'], "assists": v['Assists'], "wins": v['Wins'], "matches": v['Matches']
                    })
            return True, pd.DataFrame(rows)
        else: return False, None

    except Exception as e:
        st.error(f"Erro Fatal: {e}")
        return False, None
    finally:
        if os.path.exists(caminho_temp): os.remove(caminho_temp)

# --- 4. INTERFACE ---
st.sidebar.title("Navegação")
pagina = st.sidebar.radio("Ir para:", ["📤 Upload & Partida", "🏆 Ranking Global", "🗺️ Mapas & Radar", "📜 Histórico"], label_visibility="collapsed")

if pagina == "📤 Upload & Partida":
    st.title("📤 Upload de Demo")
    st.markdown("Suba o arquivo `.dem` para analisar a partida e enviá-la ao Ranking.")
    
    arquivo = st.file_uploader("Arraste o arquivo aqui", type=["dem"])
    if "df_partida_atual" not in st.session_state: st.session_state["df_partida_atual"] = None

    if arquivo:
        if st.button("🚀 Processar Partida"):
            with st.spinner("Analisando demo e mapa..."):
                sucesso, df_resultado = processar_demo(arquivo)
                if sucesso:
                    st.success(f"✅ Partida no mapa **{df_resultado['mapa'].iloc[0]}** salva!")
                    st.session_state["df_partida_atual"] = df_resultado
                    st.balloons()
    
    if st.session_state["df_partida_atual"] is not None:
        st.divider()
        st.subheader("📊 Relatório da Partida Atual")
        df = st.session_state["df_partida_atual"].copy()
        df['Rating'] = df.apply(lambda x: (x['kills'] + (x['assists']*0.4)) / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1) # Rating simplificado visualização rápida
        df['Resultado'] = df['wins'].apply(lambda x: "🏆 Vitória" if x == 1 else "💀 Derrota")
        df = df.sort_values(by='Rating', ascending=False)
        st.dataframe(df[['nickname', 'Resultado', 'Rating', 'kills', 'assists', 'deaths']], hide_index=True, use_container_width=True)

elif pagina == "🏆 Ranking Global":
    st.title("🏆 Ranking Global")
    
    col_top1, col_top2 = st.columns([3, 1])
    with col_top1: st.info("ℹ️ **Fator de Consistência:** Jogadores com menos de **50 partidas** sofrem penalidade.")
    with col_top2: 
        if st.button("🔄 Atualizar Dados"): st.rerun()
    
    response = supabase.table('player_stats').select("*").execute()
    db_data = pd.DataFrame(response.data) if response.data else pd.DataFrame()
    
    all_friends = pd.DataFrame({"nickname": list(AMIGOS.keys())})
    if not db_data.empty: df = pd.merge(all_friends, db_data, on="nickname", how="left")
    else: df = all_friends
        
    cols_stats = ['kills', 'deaths', 'assists', 'matches', 'wins', 'headshots', 'enemies_flashed', 'utility_damage', 'total_damage', 'rounds_played']
    for c in cols_stats:
        if c not in df.columns: df[c] = 0
    df[cols_stats] = df[cols_stats].fillna(0)

    df['KD'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
    df['WinRatePct'] = df.apply(lambda x: (x['wins'] / x['matches'] * 100) if x['matches'] > 0 else 0.0, axis=1)
    df['ADR'] = df.apply(lambda x: x['total_damage'] / x['rounds_played'] if x['rounds_played'] > 0 else 0, axis=1)
    df['RatingRaw'] = df.apply(lambda x: (x['kills'] + (x['assists']*0.4) + (x['enemies_flashed']*0.2) + (x['utility_damage']*0.01)) / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
    df['Retrospecto'] = df.apply(lambda x: f"{int(x['wins'])} / {int(x['matches'])}", axis=1)
    
    META_PARTIDAS = 50 
    df['Consistency'] = df['matches'].apply(lambda x: x / META_PARTIDAS if x < META_PARTIDAS else 1.0)
    df['RatingFinal'] = df['RatingRaw'] * df['Consistency']

    with st.expander("🔍 Filtros", expanded=False):
        sel_players = st.multiselect("Filtrar Jogadores", options=df['nickname'].unique())
        min_matches = st.slider("Mínimo de Partidas", 0, 50, 0)
    
    df_display = df[df['matches'] >= min_matches].copy()
    if sel_players: df_display = df_display[df_display['nickname'].isin(sel_players)]

    df_podium = df_display.sort_values(by='RatingFinal', ascending=False).reset_index(drop=True)
    
    if len(df_podium) >= 3 and df_podium.iloc[0]['RatingFinal'] > 0:
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col1:
            p2 = df_podium.iloc[1]
            st.markdown(f"""<div class="podium-card silver"><div style="font-size:40px;">🥈</div><div class="player-name">{p2['nickname']}</div><div class="rating-val">{p2['RatingFinal']:.2f}</div><div class="stat-row">Rating Ajustado</div></div>""", unsafe_allow_html=True)
        with col2:
            p1 = df_podium.iloc[0]
            st.markdown(f"""<div class="podium-card gold"><div style="font-size:60px;">👑</div><div class="player-name" style="color:#FFD700;">{p1['nickname']}</div><div class="rating-val" style="color:#FFD700; font-size:48px;">{p1['RatingFinal']:.2f}</div><div class="stat-row" style="color:#FFD700;">Rating Ajustado</div></div>""", unsafe_allow_html=True)
        with col3:
            p3 = df_podium.iloc[2]
            st.markdown(f"""<div class="podium-card bronze"><div style="font-size:40px;">🥉</div><div class="player-name">{p3['nickname']}</div><div class="rating-val">{p3['RatingFinal']:.2f}</div><div class="stat-row">Rating Ajustado</div></div>""", unsafe_allow_html=True)
    
    st.divider()
    st.subheader("📋 Classificação Oficial")
    st.dataframe(df_podium[['nickname', 'RatingFinal', 'RatingRaw', 'Retrospecto', 'KD', 'ADR', 'WinRatePct', 'kills', 'deaths', 'enemies_flashed', 'utility_damage']], hide_index=True, column_config={"nickname": "Jogador", "RatingFinal": st.column_config.NumberColumn("RATING OFICIAL", format="%.2f ⭐"), "WinRatePct": st.column_config.NumberColumn("Win%", format="%.0f%%")}, use_container_width=True)

    st.divider()
    with st.expander("⚠️ Área Administrativa (Encerrar Temporada)"):
        st.warning("Atenção: Isso irá salvar os dados atuais no Histórico e zerar o Ranking Global.")
        nome_season = st.text_input("Nome da Temporada para Salvar (ex: Janeiro 2026)", placeholder="Digite o nome aqui...")
        senha_admin = st.text_input("Senha Admin", type="password")
        
        if st.button("💾 ARQUIVAR E REINICIAR", type="primary"):
            if senha_admin == "admin123" and nome_season:
                if arquivar_e_resetar(nome_season):
                    st.success(f"Temporada '{nome_season}' arquivada com sucesso! O ranking foi reiniciado.")
                    st.rerun()
            else: st.error("Senha incorreta ou nome da temporada vazio.")


elif pagina == "🗺️ Mapas & Radars":
    st.title("🗺️ Mapas & Radar")
    st.markdown("Analise o desempenho e veja quais mapas precisam ser treinados.")
    
    if st.button("🔄 Carregar Mapas"): st.rerun()

    # Busca dados
    try:
        resp_maps = supabase.table('player_map_stats').select("*").execute()
    except:
        st.warning("⚠️ Tabela de mapas não encontrada.")
        resp_maps = None
    
    if resp_maps and resp_maps.data:
        df_maps = pd.DataFrame(resp_maps.data)
        
        # 1. Lista Obrigatória de Mapas (Para aparecerem mesmo zerados)
        MAPAS_OFICIAIS = ['Inferno','Overpass',  'Ancient', 'Nuke', 'Dust2','Anubis', 'Mirage']
        
        jogadores = sorted(df_maps['nickname'].unique())
        jogador_selecionado = st.selectbox("Selecione a Visão:", ["Todos (Média Geral)"] + jogadores)
        
        # 2. Lógica de Agrupamento
        if jogador_selecionado != "Todos (Média Geral)":
            # Visão Individual
            df_filtered = df_maps[df_maps['nickname'] == jogador_selecionado].copy()
            titulo_grafico = f"Performance de {jogador_selecionado}"
        else:
            # Visão de Grupo (Lógica Inteligente)
            # Agrupa por mapa
            df_grp = df_maps.groupby('map_name')
            
            # Para "Partidas": Pegamos o MÁXIMO de partidas que alguém jogou naquele mapa.
            # (Ex: Se Ph jogou 1 (Lost) e Cyrax jogou 1 (Lost), o grupo jogou 1 partida, e não 2).
            # Isso garante que a derrota conte apenas 1 vez para o grupo.
            df_matches = df_grp['matches'].max()
            
            # Para calcular a % de WinRate real, usamos a média das vitórias
            df_wins_sum = df_grp['wins'].sum()
            df_matches_sum = df_grp['matches'].sum()
            win_ratio = (df_wins_sum / df_matches_sum).fillna(0)
            
            # Recria o DataFrame do Grupo
            df_filtered = pd.DataFrame({
                'matches': df_matches,
                'wins': (df_matches * win_ratio).astype(int) # Proporcional
            }).reset_index()
            
            titulo_grafico = "Performance Geral do Grupo"

        # 3. Cruzamento com a Lista Oficial (O Pulo do Gato)
        # Cria um DF com todos os mapas vazios
        df_completo = pd.DataFrame({'map_name': MAPAS_OFICIAIS})
        # Junta com os dados reais (quem não jogou fica com 0)
        df_final = pd.merge(df_completo, df_filtered, on='map_name', how='left').fillna(0)
        
        # 4. Cálculos Finais
        # Win Rate
        df_final['WinRate'] = df_final.apply(lambda x: (x['wins'] / x['matches'] * 100) if x['matches'] > 0 else 0, axis=1)
        # Derrotas (Apenas para visualização se quiser)
        df_final['losses'] = df_final['matches'] - df_final['wins']
        
        # --- VISUALIZAÇÃO ---
        col_radar, col_barras = st.columns([1, 1])

        # A. GRÁFICO DE RADAR
        with col_radar:
            categories = df_final['map_name'].tolist()
            values = df_final['WinRate'].tolist()
            matches = df_final['matches'].tolist()
            
            categories_radar = categories + [categories[0]]
            values_radar = values + [values[0]]
            
            fig_radar = go.Figure()
            fig_radar.add_trace(go.Scatterpolar(
                r=values_radar, theta=categories_radar, fill='toself', name='Win Rate %',
                line=dict(color='#e9a338', width=3),
                fillcolor='rgba(233, 163, 56, 0.3)',
                hovertext=[f"<b>{c}</b><br>Jogos: {int(m)}<br>Vitórias: {int(v/100*m)}<br>Derrotas: {int(m - (v/100*m))}" for c, m, v in zip(categories, matches, values)] + [""]
            ))
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100], color="#8b9bb4", showticklabels=False), bgcolor="#1c222b"),
                paper_bgcolor="#0e1012", font=dict(color="#f1f1f1"), margin=dict(l=40, r=40, t=20, b=20), showlegend=False, height=400
            )
            st.markdown(f"### 🕸️ Radar de Win Rate")
            st.plotly_chart(fig_radar, use_container_width=True)

        # B. GRÁFICO DE BARRAS VERTICAIS
        with col_barras:
            # Ordena por WinRate para o gráfico
            df_barras = df_final.sort_values(by=['WinRate', 'matches'], ascending=False)
            
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(
                x=df_barras['map_name'], 
                y=df_barras['WinRate'],
                marker=dict(color=df_barras['WinRate'], colorscale='RdYlGn', cmin=0, cmax=100, showscale=False),
                text=[f"{int(m)} Jgs" if m > 0 else "" for m in df_barras['matches']], # Mostra total de jogos em cima da barra
                textposition='outside',
                hovertemplate='<b>%{x}</b><br>Win Rate: %{y:.1f}%<br>Total Partidas: %{customdata}<extra></extra>',
                customdata=df_barras['matches']
            ))
            fig_bar.update_layout(
                xaxis=dict(title="Mapas", color="#f1f1f1", gridcolor="#2d3542"),
                yaxis=dict(title="Taxa de Vitória (%)", range=[0, 115], color="#f1f1f1", gridcolor="#2d3542"),
                paper_bgcolor="#0e1012", plot_bgcolor="#0e1012", font=dict(color="#f1f1f1"),
                margin=dict(l=10, r=10, t=20, b=20), height=400
            )
            st.markdown("### 📊 Eficiência vs Quantidade")
            st.plotly_chart(fig_bar, use_container_width=True)

        # C. TABELA COMPLETA (TODOS OS MAPAS)
        st.divider()
        st.subheader("📋 Relatório Completo dos Mapas")
        
        # Mostra TODOS os mapas, ordenados pelos mais jogados primeiro
        df_show = df_final.sort_values(by=['matches', 'WinRate'], ascending=False)
        
        st.dataframe(
            df_show[['map_name', 'matches', 'wins', 'losses', 'WinRate']],
            hide_index=True,
            column_config={
                "map_name": "Mapa",
                "matches": st.column_config.NumberColumn("Partidas Totais", format="%d 🎮", help="Soma de Vitórias e Derrotas"),
                "wins": st.column_config.NumberColumn("Vitórias", format="%d 🏆"),
                "losses": st.column_config.NumberColumn("Derrotas", format="%d 💀"),
                "WinRate": st.column_config.ProgressColumn("Aproveitamento", format="%.0f%%", min_value=0, max_value=100)
            },
            use_container_width=True
        )
    else:
        st.info("Nenhuma estatística de mapa encontrada ainda. Suba partidas novas para popular o gráfico!")

elif pagina == "📜 Histórico":
    st.title("📜 Histórico de Temporadas")
    st.markdown("Consulte os campeões e estatísticas de temporadas passadas.")

    # Busca temporadas disponíveis
    try:
        resp_history = supabase.table('history_player_stats').select("season_name").execute()
        seasons = sorted(list(set([row['season_name'] for row in resp_history.data]))) if resp_history.data else []
    except: seasons = []

    if seasons:
        selected_season = st.selectbox("Selecione a Temporada:", seasons)
        
        # Carrega dados da season selecionada
        resp_data = supabase.table('history_player_stats').select("*").eq('season_name', selected_season).execute()
        df_hist = pd.DataFrame(resp_data.data)
        
        # Recalcula métricas para exibição
        df_hist['KD'] = df_hist.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        df_hist['WinRatePct'] = df_hist.apply(lambda x: (x['wins'] / x['matches'] * 100) if x['matches'] > 0 else 0.0, axis=1)
        df_hist['RatingRaw'] = df_hist.apply(lambda x: (x['kills'] + (x['assists']*0.4) + (x['enemies_flashed']*0.2) + (x['utility_damage']*0.01)) / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        
        META_PARTIDAS = 50 
        df_hist['Consistency'] = df_hist['matches'].apply(lambda x: x / META_PARTIDAS if x < META_PARTIDAS else 1.0)
        df_hist['RatingFinal'] = df_hist['RatingRaw'] * df_hist['Consistency']
        
        df_podium = df_hist.sort_values(by='RatingFinal', ascending=False).reset_index(drop=True)

        # Mostra o Campeão da Season
        if not df_podium.empty:
            champion = df_podium.iloc[0]
            st.markdown(f"""
            <div style="text-align: center; margin-bottom: 30px; padding: 20px; border: 2px solid #FFD700; border-radius: 10px; background-color: #1c222b;">
                <h2 style="color: #FFD700 !important; margin:0;">🏆 CAMPEÃO: {champion['nickname']} 🏆</h2>
                <p style="font-size: 20px; color: #fff;">Rating: {champion['RatingFinal']:.2f} • K/D: {champion['KD']:.2f}</p>
            </div>
            """, unsafe_allow_html=True)

        st.dataframe(df_podium[['nickname', 'RatingFinal', 'KD', 'WinRatePct', 'matches', 'kills', 'deaths']], hide_index=True, column_config={"RatingFinal": st.column_config.NumberColumn("Rating", format="%.2f ⭐")}, use_container_width=True)
    else:
        st.info("Nenhuma temporada arquivada ainda.")