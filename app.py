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

# --- LISTA DE AMIGOS ---
AMIGOS = {
    "Ph (Ph1L)": "76561198301569089", 
    "Pablo (Cyrax)": "76561198143002755",
    "Bruno (Safadinha)": "76561198187604726",
    "Daniel (Ocharadas)": "76561199062357951",
    "LEO (Trewan)": "76561198160033077",
    "FERNANDO (Nandin)": "76561198185508959",
    "DG (dgtremsz)":"76561199402154960",
    "Arlon (M4CH)": "76561197978110112",
}

# --- 2. FUNÇÕES AUXILIARES ---

def extrair_dados(parser, evento):
    """
    Função inteligente que 'abre o pacote' de dados do demoparser2,
    não importa se ele vem como DataFrame, lista ou tupla.
    """
    dados = parser.parse_events([evento])
    
    # Caso 1: Veio como lista de tuplas [('nome', df)] - O PROBLEMA ATUAL ERA AQUI
    if isinstance(dados, list) and len(dados) > 0 and isinstance(dados[0], tuple):
        return pd.DataFrame(dados[0][1])
    
    # Caso 2: Veio como DataFrame direto
    if isinstance(dados, pd.DataFrame):
        return dados
        
    # Caso 3: Veio como lista de dicionários (versões antigas)
    return pd.DataFrame(dados)

def atualizar_banco(stats_novos):
    progresso = st.progress(0)
    total = len(stats_novos)
    contador = 0

    for nick, dados in stats_novos.items():
        if dados['Matches'] > 0:
            response = supabase.table('player_stats').select("*").eq('nickname', nick).execute()
            
            # Prepara os dados novos
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
                # Soma com o que já tem no banco
                atual = response.data[0]
                novos_dados["kills"] += atual.get('kills', 0)
                novos_dados["deaths"] += atual.get('deaths', 0)
                novos_dados["matches"] += atual.get('matches', 0)
                novos_dados["wins"] += atual.get('wins', 0)
                novos_dados["headshots"] += atual.get('headshots', 0)
                novos_dados["enemies_flashed"] += atual.get('enemies_flashed', 0)
                novos_dados["utility_damage"] += atual.get('utility_damage', 0)
                
                supabase.table('player_stats').update(novos_dados).eq('nickname', nick).execute()
            else:
                # Cria novo registro
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
    
    # Zera as estatísticas da partida
    stats_partida = {nome: {"Kills": 0, "Deaths": 0, "Matches": 0, "Wins": 0, "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0} for nome in AMIGOS.keys()}
    sucesso = False
    
    try:
        parser = DemoParser(caminho_temp)
        
        # 1. Extração segura dos dados (usando a nova função)
        df_death = extrair_dados(parser, "player_death")
        df_blind = extrair_dados(parser, "player_blind")
        df_hurt = extrair_dados(parser, "player_hurt")
        df_round = extrair_dados(parser, "round_end")

        # --- DETETIVE DE COLUNAS ---
        # Procura qual o nome da coluna que tem o ID (pode variar)
        col_atk = None
        col_vic = None
        
        if not df_death.empty:
            cols = df_death.columns.tolist()
            # Procura variações comuns de nome de ID
            possiveis_atk = ['attacker_steamid', 'attacker_xuid', 'attacker_player_id', 'attacker_steamid64']
            possiveis_vic = ['user_steamid', 'user_xuid', 'user_player_id', 'user_steamid64']
            
            col_atk = next((c for c in cols if c in possiveis_atk), None)
            col_vic = next((c for c in cols if c in possiveis_vic), None)
            
            if not col_atk:
                st.warning(f"⚠️ Coluna de Atacante não encontrada. Colunas disponíveis: {cols}")
                return False

        # Converte IDs para texto (para garantir que bate com a lista AMIGOS)
        for df in [df_death, df_blind, df_hurt]:
            if not df.empty and col_atk and col_atk in df.columns: 
                df[col_atk] = df[col_atk].astype(str)
            if not df.empty and col_vic and col_vic in df.columns: 
                df[col_vic] = df[col_vic].astype(str)

        # 2. Lógica de Vitória (Quem ganhou a partida?)
        winning_team_num = None
        if not df_round.empty and 'winner' in df_round.columns:
            try:
                rounds_t = len(df_round[df_round['winner'] == 2])
                rounds_ct = len(df_round[df_round['winner'] == 3])
                winning_team_num = 2 if rounds_t > rounds_ct else 3
            except: pass

        # 3. Processamento dos Jogadores
        for nome_exibicao, steam_id in AMIGOS.items():
            
            if not df_death.empty and col_atk in df_death.columns:
                # Kills
                meus_kills = df_death[df_death[col_atk] == steam_id]
                stats_partida[nome_exibicao]["Kills"] = len(meus_kills)
                
                # Headshots
                if 'headshot' in meus_kills.columns:
                    stats_partida[nome_exibicao]["Headshots"] = len(meus_kills[meus_kills['headshot'] == True])
                
                # Deaths
                if col_vic in df_death.columns:
                    stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic] == steam_id])

            # Flashs
            if not df_blind.empty and col_atk in df_blind.columns:
                stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind[col_atk] == steam_id])

            # Dano de Granada (HE/Molotov)
            if not df_hurt.empty and col_atk in df_hurt.columns and 'weapon' in df_hurt.columns and 'dmg_health' in df_hurt.columns:
                granadas = ['hegrenade', 'inferno', 'incgrenade']
                meu_dano = df_hurt[
                    (df_hurt[col_atk] == steam_id) & 
                    (df_hurt['weapon'].isin(granadas))
                ]
                stats_partida[nome_exibicao]["UtilityDamage"] = int(meu_dano['dmg_health'].sum())

            # Vitória
            if winning_team_num and not df_death.empty:
                player_team = None
                # Tenta descobrir o time atacando
                if col_atk in df_death.columns and 'attacker_team_num' in df_death.columns:
                    last = df_death[df_death[col_atk] == steam_id]
                    if not last.empty: player_team = last.iloc[-1]['attacker_team_num']
                
                # Se não achou, tenta defendendo
                if not player_team and col_vic in df_death.columns and 'user_team_num' in df_death.columns:
                    last = df_death[df_death[col_vic] == steam_id]
                    if not last.empty: player_team = last.iloc[-1]['user_team_num']
                
                if player_team == winning_team_num:
                    stats_partida[nome_exibicao]["Wins"] = 1
            
            # Participação (Se matou ou morreu, conta como jogada)
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
    st.write("Suba sua demo (.dem). O sistema processa Kills, HS, Dano de Granada e Vitórias.")
    arquivo = st.file_uploader("Arquivo .dem", type=["dem"])
    
    if arquivo is not None:
        if st.button("🚀 Processar Demo"):
            with st.spinner("Processando estatísticas..."):
                if processar_demo(arquivo):
                    st.success("Sucesso! Ranking Atualizado.")
                    st.balloons()
                else:
                    st.warning("Demo processada, mas nenhum dos seus amigos foi encontrado jogando.")

with tab2:
    if st.button("🔄 Atualizar Tabela"):
        st.rerun()
        
    response = supabase.table('player_stats').select("*").execute()
    
    if response.data:
        df = pd.DataFrame(response.data)
        
        # Garante que as colunas existem (preenche com 0 se faltar)
        cols_esperadas = ['kills', 'deaths', 'matches', 'wins', 'headshots', 'utility_damage', 'enemies_flashed']
        for col in cols_esperadas:
            if col not in df.columns: df[col] = 0
        
        # Cálculos de Porcentagem
        df['KD'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        df['Win%'] = df.apply(lambda x: (x['wins'] / x['matches'] * 100) if x['matches'] > 0 else 0, axis=1)
        df['HS%'] = df.apply(lambda x: (x['headshots'] / x['kills'] * 100) if x['kills'] > 0 else 0, axis=1)
        
        # Ordenação
        df = df.sort_values(by='KD', ascending=False)
        
        # Exibição Bonita
        st.dataframe(
            df[['nickname', 'KD', 'Win%', 'kills', 'deaths', 'matches', 'HS%', 'utility_damage']],
            hide_index=True,
            column_config={
                "nickname": "Jogador",
                "KD": st.column_config.NumberColumn("K/D", format="%.2f ⭐"),
                "Win%": st.column_config.NumberColumn("Win Rate", format="%.0f%% 🏆"),
                "HS%": st.column_config.NumberColumn("HS Rate", format="%.0f%% 🎯"),
                "utility_damage": st.column_config.NumberColumn("Dano Util", format="%.0f 💣"),
                "kills": "Kills",
                "deaths": "Mortes",
                "matches": "Partidas"
            },
            use_container_width=True
        )
    else:
        st.info("O Ranking está vazio. Suba a primeira demo!")