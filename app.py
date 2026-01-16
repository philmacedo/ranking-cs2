import streamlit as st
import pandas as pd
import os
import tempfile
from demoparser2 import DemoParser

st.set_page_config(page_title="CS2 Debugger", page_icon="🐞", layout="wide")

# --- LISTA DE AMIGOS (Copie sua lista aqui) ---
AMIGOS = {
    "Ph (Ph1L)": ["76561198301569089", "76561198051052379"],
    "Pablo (Cyrax)": ["76561198143002755", "76561198446160415"],
    "Bruno (Safadinha)": ["76561198187604726"],
    "Daniel (Ocharadas)": ["76561199062357951"],
}

def normalizar_time(valor):
    try:
        s = str(valor).upper().strip().replace('.0', '')
        if s in ['CT', '3']: return '3' # CT
        if s in ['T', 'TERRORIST', '2']: return '2' # TR
        return f"DESCONHECIDO ({s})"
    except: return "ERRO"

def extrair_dados(parser, evento):
    try:
        dados = parser.parse_events([evento])
        if isinstance(dados, list) and len(dados) > 0: return pd.DataFrame(dados[0][1])
        return pd.DataFrame(dados)
    except: return pd.DataFrame()

st.title("🐞 Debugger de Vitória CS2")
st.write("Vamos descobrir por que o sistema acha que você perdeu.")

arquivo = st.file_uploader("Suba a demo 'vitoriosa' que está dando erro", type=["dem"])

if arquivo:
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo.read())
    caminho = tfile.name
    tfile.close()

    parser = DemoParser(caminho)

    # --- PASSO 1: QUEM GANHOU O JOGO? ---
    st.header("1. Análise do Vencedor (Placar)")
    df_round = extrair_dados(parser, "round_end")
    
    winning_team = None
    
    if not df_round.empty and 'winner' in df_round.columns:
        # Mostra os dados crus para vermos o formato
        st.write("Dados crus dos últimos 5 rounds:")
        st.dataframe(df_round[['tick', 'winner', 'reason']].tail(5))
        
        df_round['time_normalizado'] = df_round['winner'].apply(normalizar_time)
        rounds_tr = len(df_round[df_round['time_normalizado'] == '2'])
        rounds_ct = len(df_round[df_round['time_normalizado'] == '3'])
        
        col1, col2 = st.columns(2)
        col1.metric("Rounds Time 2 (TR)", rounds_tr)
        col2.metric("Rounds Time 3 (CT)", rounds_ct)
        
        if rounds_tr > rounds_ct: winning_team = '2'
        elif rounds_ct > rounds_tr: winning_team = '3'
        
        if winning_team:
            st.success(f"🏆 O Código decidiu que o vencedor foi: **TIME {winning_team}**")
        else:
            st.error("❌ O Código achou que foi EMPATE ou não conseguiu ler.")
    else:
        st.error("Não encontrei eventos de 'round_end'!")

    # --- PASSO 2: ONDE ESTAVAM SEUS AMIGOS? ---
    st.header("2. Análise dos Jogadores (Linha do Tempo)")
    
    df_death = extrair_dados(parser, "player_death")
    df_spawn = extrair_dados(parser, "player_spawn")
    
    # Detetive de colunas
    col_atk = None
    if not df_death.empty:
        cols = df_death.columns.tolist()
        col_atk = next((c for c in cols if c in ['attacker_steamid', 'attacker_xuid', 'attacker_steamid64']), None)
        
    col_spawn_id = None
    if not df_spawn.empty:
        col_spawn_id = next((c for c in df_spawn.columns if c in ['user_steamid', 'steamid', 'user_xuid']), None)

    if not col_atk:
        st.error("Não consegui ler os IDs na demo.")
    else:
        # Processa cada amigo
        for nome, lista_ids in AMIGOS.items():
            st.subheader(f"👤 Investigando: {nome}")
            lista_ids = [str(uid).strip() for uid in lista_ids]
            
            # Limpa dados da demo
            if col_atk in df_death.columns:
                df_death[col_atk] = df_death[col_atk].astype(str).str.replace('.0', '')
            if col_spawn_id and col_spawn_id in df_spawn.columns:
                df_spawn[col_spawn_id] = df_spawn[col_spawn_id].astype(str).str.replace('.0', '')

            # Constrói histórico
            historico = []
            
            # 1. Spawns
            if not df_spawn.empty and col_spawn_id:
                meus_spawns = df_spawn[df_spawn[col_spawn_id].isin(lista_ids)]
                for _, row in meus_spawns.iterrows():
                    t = "Desconhecido"
                    if 'team_num' in row: t = normalizar_time(row['team_num'])
                    elif 'user_team_num' in row: t = normalizar_time(row['user_team_num'])
                    historico.append({'tick': row['tick'], 'evento': 'Spawn', 'time': t})
            
            # 2. Mortes/Kills
            if not df_death.empty:
                meus_eventos = df_death[df_death[col_atk].isin(lista_ids)]
                for _, row in meus_eventos.iterrows():
                    t = "Desconhecido"
                    if 'attacker_team_num' in row: t = normalizar_time(row['attacker_team_num'])
                    historico.append({'tick': row['tick'], 'evento': 'Kill/Death', 'time': t})

            # Analisa o último momento
            if historico:
                df_hist = pd.DataFrame(historico).sort_values('tick')
                ultimo_estado = df_hist.iloc[-1]
                ultimo_time = ultimo_estado['time']
                
                st.write("**Últimos 3 eventos registrados:**")
                st.dataframe(df_hist.tail(3))
                
                cor = "green" if ultimo_time == winning_team else "red"
                resultado = "VITÓRIA" if ultimo_time == winning_team else "DERROTA"
                
                st.markdown(f"""
                * Time Vencedor da Partida: **{winning_team}**
                * Time Final do Jogador: **{ultimo_time}**
                * Conclusão do Código: :{cor}[**{resultado}**]
                """)
                
                if ultimo_time != winning_team:
                    st.warning(f"⚠️ PROBLEMA: O jogador terminou no time {ultimo_time}, mas quem ganhou foi o {winning_team}.")
            else:
                st.warning("⚠️ Jogador não encontrado nesta demo (nenhum evento de spawn ou kill).")

    os.remove(caminho)