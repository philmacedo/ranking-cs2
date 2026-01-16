import streamlit as st
import pandas as pd
import os
import tempfile
from supabase import create_client, Client
from demoparser2 import DemoParser

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="CS2 Pro Ranking - Auditoria", page_icon="🕵️", layout="wide")

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
def extrair_dados(parser, evento):
    dados = parser.parse_events([evento])
    if isinstance(dados, list) and len(dados) > 0 and isinstance(dados[0], tuple):
        return pd.DataFrame(dados[0][1])
    if isinstance(dados, pd.DataFrame):
        return dados
    return pd.DataFrame(dados)

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

            if response.data:
                atual = response.data[0]
                for k in novos_dados: novos_dados[k] += atual.get(k, 0)
                supabase.table('player_stats').update(novos_dados).eq('nickname', nick).execute()
            else:
                novos_dados["nickname"] = nick
                supabase.table('player_stats').insert(novos_dados).execute()
        progresso.progress((i + 1) / total)
    progresso.empty()

def processar_demo(arquivo_upload):
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo_upload.read())
    caminho_temp = tfile.name
    tfile.close()
    
    stats_partida = {nome: {"Kills": 0, "Deaths": 0, "Matches": 0, "Wins": 0, "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0} for nome in AMIGOS.keys()}
    sucesso = False
    
    # Lista para relatório de auditoria na tela
    auditoria = []

    try:
        parser = DemoParser(caminho_temp)
        
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
            st.error("Erro Crítico: Não foi possível ler os IDs da demo.")
            return False

        # Limpeza de IDs
        for df in [df_death, df_blind, df_hurt]:
            if not df.empty and col_atk in df.columns: 
                df[col_atk] = df[col_atk].astype(str).str.replace(r'\.0$', '', regex=True)
            if not df.empty and col_vic in df.columns: 
                df[col_vic] = df[col_vic].astype(str).str.replace(r'\.0$', '', regex=True)

        # --- AUDITORIA DE PLACAR ---
        winning_team_str = "Indefinido"
        if not df_round.empty and 'winner' in df_round.columns:
            # Força conversão para string para contar certo
            rounds_t = len(df_round[df_round['winner'].astype(str).isin(['2', '2.0'])])
            rounds_ct = len(df_round[df_round['winner'].astype(str).isin(['3', '3.0'])])
            
            st.divider()
            col1, col2, col3 = st.columns(3)
            col1.metric("Rounds TR (Time 2)", rounds_t)
            col2.metric("Rounds CT (Time 3)", rounds_ct)
            
            if rounds_t > rounds_ct: winning_team_str = "2"
            elif rounds_ct > rounds_t: winning_team_str = "3"
            else: winning_team_str = "Empate"
            
            col3.metric("Vencedor Calculado", f"Time {winning_team_str}")

        # --- PROCESSAMENTO ---
        for nome_exibicao, lista_ids in AMIGOS.items():
            lista_ids = [str(uid).strip() for uid in lista_ids]
            
            # KILLS
            if not df_death.empty and col_atk in df_death.columns:
                meus_kills = df_death[df_death[col_atk].isin(lista_ids)]
                stats_partida[nome_exibicao]["Kills"] = len(meus_kills)
                if 'headshot' in meus_kills.columns:
                    stats_partida[nome_exibicao]["Headshots"] = len(meus_kills[meus_kills['headshot'] == True])
                if col_vic in df_death.columns:
                    stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic].isin(lista_ids)])

            # FLASH & DANO
            if not df_blind.empty and col_atk in df_blind.columns:
                stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind[col_atk].isin(lista_ids)])
            if not df_hurt.empty and col_atk in df_hurt.columns and 'weapon' in df_hurt.columns:
                dmg = df_hurt[(df_hurt[col_atk].isin(lista_ids)) & (df_hurt['weapon'].isin(['hegrenade', 'inferno', 'incgrenade']))]
                stats_partida[nome_exibicao]["UtilityDamage"] = int(dmg['dmg_health'].sum())

            # --- AUDITORIA DE TIME (O PULO DO GATO) ---
            player_team_str = "Não Achou"
            
            if not df_death.empty:
                # Tenta achar o time em que ele estava quando matou alguém
                if col_atk in df_death.columns and 'attacker_team_num' in df_death.columns:
                    last_atk = df_death[df_death[col_atk].isin(lista_ids)]
                    if not last_atk.empty: 
                        raw_team = last_atk.iloc[-1]['attacker_team_num']
                        player_team_str = str(int(float(raw_team))) # Limpa 2.0 -> "2"
                
                # Se não achou, tenta achar o time em que ele estava quando morreu
                if player_team_str == "Não Achou" and col_vic in df_death.columns and 'user_team_num' in df_death.columns:
                    last_vic = df_death[df_death[col_vic].isin(lista_ids)]
                    if not last_vic.empty: 
                        raw_team = last_vic.iloc[-1]['user_team_num']
                        player_team_str = str(int(float(raw_team)))

            # CHECK FINAL DE VITÓRIA
            is_win = False
            if winning_team_str != "Indefinido" and winning_team_str != "Empate":
                if player_team_str == winning_team_str:
                    stats_partida[nome_exibicao]["Wins"] = 1
                    is_win = True
            
            # Adiciona ao relatório
            if stats_partida[nome_exibicao]["Kills"] > 0 or stats_partida[nome_exibicao]["Deaths"] > 0:
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True
                auditoria.append({
                    "Jogador": nome_exibicao,
                    "Time Detectado": player_team_str,
                    "Time Vencedor": winning_team_str,
                    "Ganhou?": "✅ SIM" if is_win else "❌ NÃO"
                })

        # EXIBE A AUDITORIA NA TELA
        if auditoria:
            st.write("### 🕵️ Auditoria da Partida")
            st.dataframe(pd.DataFrame(auditoria), use_container_width=True)
            atualizar_banco(stats_partida)

    except Exception as e:
        st.error(f"Erro ao processar: {e}")
    finally:
        os.remove(caminho_temp)
    return sucesso

# --- 3. INTERFACE ---
st.title("🔥 CS2 Pro Ranking - Auditoria")
tab1, tab2 = st.tabs(["📤 Upload", "🏆 Ranking"])

with tab1:
    arquivo = st.file_uploader("Arquivo .dem", type=["dem"])
    if arquivo and st.button("🚀 Processar Demo"):
        with st.spinner("Analisando..."):
            if processar_demo(arquivo):
                st.success("Dados salvos!")
            else:
                st.warning("Nenhum amigo encontrado.")

with tab2:
    if st.button("🔄 Atualizar Tabela"): st.rerun()
    response = supabase.table('player_stats').select("*").execute()
    if response.data:
        df = pd.DataFrame(response.data)
        for col in ['kills', 'deaths', 'matches', 'wins', 'headshots', 'utility_damage', 'enemies_flashed']:
            if col not in df.columns: df[col] = 0
            
        df['KD'] = df.apply(lambda x: x['kills']/x['deaths'] if x['deaths']>0 else x['kills'], axis=1)
        df['Win%'] = df.apply(lambda x: (x['wins']/x['matches']*100) if x['matches']>0 else 0, axis=1)
        
        st.dataframe(df[['nickname', 'KD', 'Win%', 'kills', 'deaths', 'matches', 'enemies_flashed']], hide_index=True)
    else:
        st.info("Ranking vazio.")