import streamlit as st
import pandas as pd
import os
import tempfile
from supabase import create_client, Client
from demoparser2 import DemoParser

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="CS2 Pro Ranking", page_icon="🔫", layout="wide")

try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
except FileNotFoundError:
    st.error("❌ Erro: Secrets não encontrados.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- LISTA DE AMIGOS (COM SMURFS) ---
AMIGOS = {
    "Ph (Ph1L)": ["76561198301569089", "76561198000000000"], 
    "Pablo (Cyrax)": ["76561198143002755", "76561199999999999"],
    "Bruno (Safadinha)": ["76561198187604726"],
    "Daniel (Ocharadas)": ["76561199062357951"],
    "LEO (Trewan)": ["76561198160033077"],
    "FERNANDO (Nandin)": ["76561198185508959"],
    "DG (dgtremsz)": ["76561199402154960"],
    "Arlon (M4CH)": ["76561197978110112"],
}

# --- 2. FUNÇÕES AUXILIARES ---

def extrair_dados(parser, evento):
    """Abre o pacote de dados do demoparser2 de forma segura"""
    dados = parser.parse_events([evento])
    if isinstance(dados, list) and len(dados) > 0 and isinstance(dados[0], tuple):
        return pd.DataFrame(dados[0][1])
    if isinstance(dados, pd.DataFrame):
        return dados
    return pd.DataFrame(dados)

def atualizar_banco(stats_novos):
    progresso = st.progress(0)
    total = len(stats_novos)
    contador = 0

    for nick, dados in stats_novos.items():
        if dados['Matches'] > 0:
            response = supabase.table('player_stats').select("*").eq('nickname', nick).execute()
            
            novos_dados = {
                "kills": dados['Kills'],
                "deaths": dados['Deaths'],
                "matches": dados['Matches'],
                "wins": dados['Wins'],
                "headshots": dados['Headshots'],
                "enemies_flashed": dados['EnemiesFlashed'],
                "utility_damage": dados['UtilityDamage']
            }

            if response.data:
                atual = response.data[0]
                # Soma com o que já tem no banco
                novos_dados["kills"] += atual.get('kills', 0)
                novos_dados["deaths"] += atual.get('deaths', 0)
                novos_dados["matches"] += atual.get('matches', 0)
                novos_dados["wins"] += atual.get('wins', 0)
                novos_dados["headshots"] += atual.get('headshots', 0)
                novos_dados["enemies_flashed"] += atual.get('enemies_flashed', 0)
                novos_dados["utility_damage"] += atual.get('utility_damage', 0)
                
                supabase.table('player_stats').update(novos_dados).eq('nickname', nick).execute()
            else:
                novos_dados["nickname"] = nick
                supabase.table('player_stats').insert(novos_dados).execute()
        
        contador += 1
        progresso.progress(contador / total)
    progresso.empty()

def processar_demo(arquivo_upload):
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo_upload.read())
    caminho_temp = tfile.name
    tfile.close()
    
    stats_partida = {nome: {"Kills": 0, "Deaths": 0, "Matches": 0, "Wins": 0, "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0} for nome in AMIGOS.keys()}
    sucesso = False
    
    try:
        parser = DemoParser(caminho_temp)
        
        # 1. Extração
        df_death = extrair_dados(parser, "player_death")
        df_blind = extrair_dados(parser, "player_blind")
        df_hurt = extrair_dados(parser, "player_hurt")
        df_round = extrair_dados(parser, "round_end")

        # --- DETETIVE DE COLUNAS ---
        col_atk, col_vic = None, None
        
        if not df_death.empty:
            cols = df_death.columns.tolist()
            possiveis_atk = ['attacker_steamid', 'attacker_xuid', 'attacker_player_id', 'attacker_steamid64']
            possiveis_vic = ['user_steamid', 'user_xuid', 'user_player_id', 'user_steamid64']
            
            col_atk = next((c for c in cols if c in possiveis_atk), None)
            col_vic = next((c for c in cols if c in possiveis_vic), None)
            
            if not col_atk:
                st.warning(f"⚠️ IDs não encontrados. Colunas: {cols}")
                return False

        # Converte IDs para texto limpo nos DataFrames
        for df in [df_death, df_blind, df_hurt]:
            if not df.empty and col_atk in df.columns: 
                df[col_atk] = df[col_atk].astype(str).str.replace(r'\.0$', '', regex=True)
            if not df.empty and col_vic in df.columns: 
                df[col_vic] = df[col_vic].astype(str).str.replace(r'\.0$', '', regex=True)

        # 2. Lógica de Vitória (Melhorada)
        winning_team_num = None
        if not df_round.empty and 'winner' in df_round.columns:
            try:
                rounds_t = len(df_round[df_round['winner'] == 2])
                rounds_ct = len(df_round[df_round['winner'] == 3])
                winning_team_num = 2 if rounds_t > rounds_ct else 3
                
                # Debug na tela para conferir
                vencedor_texto = "TR (2)" if winning_team_num == 2 else "CT (3)"
                st.caption(f"🏁 Placar detectado: TR {rounds_t} x {rounds_ct} CT. Vencedor: {vencedor_texto}")
            except: 
                st.warning("Não foi possível calcular o placar.")

        # 3. Processamento (Iterando corretamente sobre a LISTA de IDs)
        for nome_exibicao, lista_ids in AMIGOS.items():
            
            # Limpa IDs da lista
            lista_ids = [str(uid).strip() for uid in lista_ids]

            if not df_death.empty and col_atk in df_death.columns:
                # Kills: Usa .isin() para checar se algum dos IDs da lista matou
                meus_kills = df_death[df_death[col_atk].isin(lista_ids)]
                stats_partida[nome_exibicao]["Kills"] = len(meus_kills)
                
                if 'headshot' in meus_kills.columns:
                    stats_partida[nome_exibicao]["Headshots"] = len(meus_kills[meus_kills['headshot'] == True])
                
                # Deaths: Usa .isin()
                if col_vic in df_death.columns:
                    stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic].isin(lista_ids)])

            # Flashs
            if not df_blind.empty and col_atk in df_blind.columns:
                stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind[col_atk].isin(lista_ids)])

            # Dano
            if not df_hurt.empty and col_atk in df_hurt.columns and 'weapon' in df_hurt.columns and 'dmg_health' in df_hurt.columns:
                granadas = ['hegrenade', 'inferno', 'incgrenade']
                meu_dano = df_hurt[
                    (df_hurt[col_atk].isin(lista_ids)) & 
                    (df_hurt['weapon'].isin(granadas))
                ]
                stats_partida[nome_exibicao]["UtilityDamage"] = int(meu_dano['dmg_health'].sum())

            # Vitória (Correção Crítica de Tipos)
            if winning_team_num and not df_death.empty:
                player_team = None
                
                # Procura time do jogador (Atacando)
                if col_atk in df_death.columns and 'attacker_team_num' in df_death.columns:
                    last = df_death[df_death[col_atk].isin(lista_ids)]
                    if not last.empty: 
                        player_team = last.iloc[-1]['attacker_team_num']
                
                # Procura time do jogador (Defendendo)
                if not player_team and col_vic in df_death.columns and 'user_team_num' in df_death.columns:
                    last = df_death[df_death[col_vic].isin(lista_ids)]
                    if not last.empty: 
                        player_team = last.iloc[-1]['user_team_num']
                
                # Compara garantindo que ambos são inteiros
                if player_team is not None:
                    try:
                        if int(float(player_team)) == int(winning_team_num):
                            stats_partida[nome_exibicao]["Wins"] = 1
                    except: pass
            
            # Participação
            if stats_partida[nome_exibicao]["Kills"] > 0 or stats_partida[nome_exibicao]["Deaths"] > 0:
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True

        if sucesso:
            atualizar_banco(stats_partida)

    except Exception as e:
        st.error(f"Erro ao processar: {e}")
    finally:
        os.remove(caminho_temp)
    return sucesso

# --- 3. INTERFACE ---
st.title("🔥 CS2 Pro Ranking")

tab1, tab2 = st.tabs(["📤 Upload", "🏆 Ranking"])

with tab1:
    st.write("Suba sua demo.")
    arquivo = st.file_uploader("Arquivo .dem", type=["dem"])
    
    if arquivo is not None:
        if st.button("🚀 Processar Demo"):
            with st.spinner("Analisando..."):
                if processar_demo(arquivo):
                    st.success("Sucesso! Estatísticas computadas.")
                    st.balloons()
                else:
                    st.warning("Nenhum amigo encontrado.")

with tab2:
    if st.button("🔄 Atualizar Tabela"):
        st.rerun()
        
    response = supabase.table('player_stats').select("*").execute()
    
    if response.data:
        df = pd.DataFrame(response.data)
        
        # Garante colunas e preenche vazios com 0
        cols_esperadas = ['kills', 'deaths', 'matches', 'wins', 'headshots', 'utility_damage', 'enemies_flashed']
        for col in cols_esperadas:
            if col not in df.columns: df[col] = 0
            df[col] = df[col].fillna(0) # Previne erro de nulo
        
        # Cálculos
        df['KD'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        df['Win%'] = df.apply(lambda x: (x['wins'] / x['matches'] * 100) if x['matches'] > 0 else 0, axis=1)
        df['HS%'] = df.apply(lambda x: (x['headshots'] / x['kills'] * 100) if x['kills'] > 0 else 0, axis=1)
        
        # Ordenação
        df = df.sort_values(by='KD', ascending=False)
        
        # --- TABELA FINAL (COM INIMIGOS CEGOS) ---
        st.dataframe(
            df[['nickname', 'KD', 'Win%', 'enemies_flashed', 'kills', 'deaths', 'matches', 'HS%', 'utility_damage']],
            hide_index=True,
            column_config={
                "nickname": "Jogador",
                "KD": st.column_config.NumberColumn("K/D", format="%.2f ⭐"),
                "Win%": st.column_config.NumberColumn("Win Rate", format="%.0f%% 🏆"),
                "enemies_flashed": st.column_config.NumberColumn("Cegos", format="%d 💡"),
                "HS%": st.column_config.NumberColumn("HS Rate", format="%.0f%% 🎯"),
                "utility_damage": st.column_config.NumberColumn("Dano Util", format="%.0f 💣"),
            },
            use_container_width=True
        )
    else:
        st.info("Ranking vazio.")