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

# --- 2. FUNÇÕES DE PROTEÇÃO (HASH) ---

def calcular_hash(arquivo_bytes):
    """Gera uma impressão digital única (MD5) para o arquivo"""
    return hashlib.md5(arquivo_bytes).hexdigest()

def demo_ja_processada(file_hash):
    """Verifica no banco se essa demo já existe"""
    try:
        response = supabase.table('processed_matches').select('match_hash').eq('match_hash', file_hash).execute()
        return len(response.data) > 0
    except Exception as e:
        st.error(f"Erro ao verificar duplicidade: {e}")
        return False

def registrar_demo(file_hash):
    """Salva a digital da demo para bloquear envios futuros"""
    try:
        supabase.table('processed_matches').insert({'match_hash': file_hash}).execute()
    except Exception as e:
        st.warning(f"Aviso: Não foi possível registrar o hash da demo: {e}")

# --- 3. FUNÇÕES DE DADOS ---

def extrair_dados(parser, evento):
    dados = parser.parse_events([evento])
    if isinstance(dados, list) and len(dados) > 0 and isinstance(dados[0], tuple):
        return pd.DataFrame(dados[0][1])
    if isinstance(dados, pd.DataFrame): return dados
    return pd.DataFrame(dados)

def atualizar_banco(stats_novos):
    progresso = st.progress(0)
    total = len(stats_novos)
    
    for i, (nick, dados) in enumerate(stats_novos.items()):
        if dados['Matches'] > 0:
            # 1. Busca dados atuais do jogador
            response = supabase.table('player_stats').select("*").eq('nickname', nick).execute()
            
            # 2. Prepara o pacote de dados novos (SEM WINS)
            novos_dados = {
                "kills": dados['Kills'],
                "deaths": dados['Deaths'],
                "matches": dados['Matches'],
                "headshots": dados['Headshots'],
                "enemies_flashed": dados['EnemiesFlashed'],
                "utility_damage": dados['UtilityDamage']
            }

            try:
                if response.data:
                    # UPDATE: Soma com o que já existe
                    atual = response.data[0]
                    for k in novos_dados:
                        # .get(k, 0) protege contra colunas nulas
                        novos_dados[k] += atual.get(k, 0)
                    
                    supabase.table('player_stats').update(novos_dados).eq('nickname', nick).execute()
                else:
                    # INSERT: Cria novo jogador
                    novos_dados["nickname"] = nick
                    # Garante que 'wins' inicie zerado se criar agora
                    novos_dados["wins"] = 0 
                    supabase.table('player_stats').insert(novos_dados).execute()
                    
            except Exception as e:
                st.error(f"Erro ao salvar dados de {nick}: {e}")

        progresso.progress((i + 1) / total)
    progresso.empty()

def processar_demo(arquivo_upload):
    # --- A. PROTEÇÃO CONTRA DUPLICATAS ---
    # Lê o arquivo para a memória
    arquivo_bytes = arquivo_upload.read()
    
    # Calcula o Hash
    file_hash = calcular_hash(arquivo_bytes)
    
    # Pergunta ao banco
    if demo_ja_processada(file_hash):
        st.error("⛔ **Demo Duplicada!** Esta partida já foi computada anteriormente.")
        st.stop() # Para o código aqui mesmo

    # --- B. PREPARAÇÃO ---
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo_bytes)
    caminho_temp = tfile.name
    tfile.close()
    
    stats_partida = {nome: {"Kills": 0, "Deaths": 0, "Matches": 0, "Headshots": 0, "EnemiesFlashed": 0, "UtilityDamage": 0} for nome in AMIGOS.keys()}
    sucesso = False
    
    try:
        parser = DemoParser(caminho_temp)
        
        # Leitura apenas do essencial
        df_death = extrair_dados(parser, "player_death")
        df_blind = extrair_dados(parser, "player_blind")
        df_hurt = extrair_dados(parser, "player_hurt")

        # --- C. DETETIVE DE COLUNAS ---
        col_atk, col_vic = None, None
        if not df_death.empty:
            cols = df_death.columns.tolist()
            possiveis_atk = ['attacker_steamid', 'attacker_xuid', 'attacker_player_id', 'attacker_steamid64']
            possiveis_vic = ['user_steamid', 'user_xuid', 'user_player_id', 'user_steamid64']
            col_atk = next((c for c in cols if c in possiveis_atk), None)
            col_vic = next((c for c in cols if c in possiveis_vic), None)

        if not col_atk:
            st.warning("⚠️ Não foi possível ler os IDs dos jogadores nesta demo.")
            return False

        # Limpeza de IDs (remove .0 se existir)
        for df in [df_death, df_blind, df_hurt]:
            if not df.empty and col_atk in df.columns: 
                df[col_atk] = df[col_atk].astype(str).str.replace(r'\.0$', '', regex=True)
            if not df.empty and col_vic in df.columns: 
                df[col_vic] = df[col_vic].astype(str).str.replace(r'\.0$', '', regex=True)

        # --- D. CÁLCULOS (SEM WIN RATE) ---
        for nome_exibicao, lista_ids in AMIGOS.items():
            lista_ids = [str(uid).strip() for uid in lista_ids]
            
            # 1. Kills e HS
            if not df_death.empty and col_atk in df_death.columns:
                meus_kills = df_death[df_death[col_atk].isin(lista_ids)]
                stats_partida[nome_exibicao]["Kills"] = len(meus_kills)
                
                if 'headshot' in meus_kills.columns:
                    stats_partida[nome_exibicao]["Headshots"] = len(meus_kills[meus_kills['headshot'] == True])
                
                # Mortes
                if col_vic in df_death.columns:
                    stats_partida[nome_exibicao]["Deaths"] = len(df_death[df_death[col_vic].isin(lista_ids)])

            # 2. Cegos (Flashed)
            if not df_blind.empty and col_atk in df_blind.columns:
                stats_partida[nome_exibicao]["EnemiesFlashed"] = len(df_blind[df_blind[col_atk].isin(lista_ids)])
            
            # 3. Dano de Utilitário
            if not df_hurt.empty and col_atk in df_hurt.columns and 'weapon' in df_hurt.columns:
                dmg = df_hurt[
                    (df_hurt[col_atk].isin(lista_ids)) & 
                    (df_hurt['weapon'].isin(['hegrenade', 'inferno', 'incgrenade']))
                ]
                stats_partida[nome_exibicao]["UtilityDamage"] = int(dmg['dmg_health'].sum())

            # Check de Participação
            if stats_partida[nome_exibicao]["Kills"] > 0 or stats_partida[nome_exibicao]["Deaths"] > 0:
                stats_partida[nome_exibicao]["Matches"] = 1
                sucesso = True

        # --- E. FINALIZAÇÃO ---
        if sucesso:
            atualizar_banco(stats_partida)
            registrar_demo(file_hash) # <--- AQUI BLOQUEIA O REENVIO FUTURO

    except Exception as e:
        st.error(f"Erro no processamento: {e}")
    finally:
        os.remove(caminho_temp)
    return sucesso

# --- 4. INTERFACE ---
st.title("🔥 CS2 Pro Ranking")
st.caption("Sistema protegido contra demos duplicadas 🛡️")

tab1, tab2 = st.tabs(["📤 Upload", "🏆 Ranking"])

with tab1:
    arquivo = st.file_uploader("Arquivo .dem", type=["dem"])
    
    if arquivo is not None:
        if st.button("🚀 Processar Demo"):
            with st.spinner("Analisando e verificando duplicatas..."):
                if processar_demo(arquivo):
                    st.success("✅ Demo processada e salva com sucesso!")
                    st.balloons()
                # Se for duplicada, o aviso aparece dentro da função processar_demo

with tab2:
    if st.button("🔄 Atualizar Tabela"):
        st.rerun()
        
    response = supabase.table('player_stats').select("*").execute()
    
    if response.data:
        df = pd.DataFrame(response.data)
        
        # Garante colunas essenciais
        cols_check = ['kills', 'deaths', 'matches', 'headshots', 'utility_damage', 'enemies_flashed']
        for col in cols_check:
            if col not in df.columns: df[col] = 0
            
        # Cálculos de Rate
        df['KD'] = df.apply(lambda x: x['kills'] / x['deaths'] if x['deaths'] > 0 else x['kills'], axis=1)
        df['HS%'] = df.apply(lambda x: (x['headshots'] / x['kills'] * 100) if x['kills'] > 0 else 0, axis=1)
        
        # Removemos Win% da visualização já que paramos de calcular
        df = df.sort_values(by='KD', ascending=False)
        
        st.dataframe(
            df[['nickname', 'KD', 'kills', 'deaths', 'matches', 'HS%', 'enemies_flashed', 'utility_damage']],
            hide_index=True,
            column_config={
                "nickname": "Jogador",
                "KD": st.column_config.NumberColumn("K/D", format="%.2f ⭐"),
                "HS%": st.column_config.NumberColumn("HS %", format="%.0f%% 🎯"),
                "enemies_flashed": st.column_config.NumberColumn("Cegos 💡", format="%d"),
                "utility_damage": st.column_config.NumberColumn("Dano Util 💣", format="%d"),
                "kills": "Kills",
                "deaths": "Mortes",
                "matches": "Partidas"
            },
            use_container_width=True
        )
    else:
        st.info("Ranking vazio.")