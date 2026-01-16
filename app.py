import streamlit as st
import pandas as pd
import os
import tempfile
from demoparser2 import DemoParser

st.set_page_config(page_title="CS2 Lab", page_icon="🔬", layout="wide")

st.title("🔬 Laboratório de Demos CS2")
st.warning("Este modo é apenas para descobrir como sua demo salva a vitória.")

# Upload
arquivo = st.file_uploader("Suba a demo problemática", type=["dem"])

if arquivo:
    # Salva temporário
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".dem")
    tfile.write(arquivo.read())
    caminho = tfile.name
    tfile.close()

    try:
        parser = DemoParser(caminho)

        # --- 1. QUEM GANHOU OS ROUNDS? ---
        st.header("1. Análise de Rounds (round_end)")
        try:
            df_round = pd.DataFrame(parser.parse_events(["round_end"]))
            
            if not df_round.empty and 'winner' in df_round.columns:
                # Contagem
                vitorias_tr = len(df_round[df_round['winner'].astype(str).isin(['2', '2.0'])])
                vitorias_ct = len(df_round[df_round['winner'].astype(str).isin(['3', '3.0'])])
                
                col1, col2 = st.columns(2)
                col1.metric("Vitórias TR (Time 2)", vitorias_tr)
                col2.metric("Vitórias CT (Time 3)", vitorias_ct)
                
                st.write("👇 **Dados Crus dos Rounds:**")
                st.dataframe(df_round.head(30), use_container_width=True)
            else:
                st.error("❌ Não achei a coluna 'winner' no evento round_end.")
                st.write("Colunas encontradas:", df_round.columns.tolist())
        except Exception as e:
            st.error(f"Erro ao ler rounds: {e}")

        # --- 2. O EVENTO DE FIM DE JOGO ---
        st.header("2. O Evento Final (cs_win_panel_match)")
        st.info("Este evento costuma aparecer apenas UMA VEZ no fim do jogo e diz o vencedor oficial.")
        
        try:
            # Tenta ler o evento específico de vitória do CS2
            df_win = pd.DataFrame(parser.parse_events(["cs_win_panel_match"]))
            
            if not df_win.empty:
                st.success("✅ Evento de fim de jogo ENCONTRADO!")
                st.dataframe(df_win, use_container_width=True)
            else:
                st.warning("⚠️ Evento 'cs_win_panel_match' não encontrado ou vazio.")
                
        except Exception as e:
            st.write(f"Não foi possível ler cs_win_panel_match: {e}")

        # --- 3. EM QUE TIME SEUS AMIGOS ESTAVAM? ---
        st.header("3. Times dos Jogadores")
        st.info("O sistema precisa saber se seus amigos eram TR (2) ou CT (3).")
        
        df_death = pd.DataFrame(parser.parse_events(["player_death"]))
        if not df_death.empty:
            # Procura coluna de ID
            cols = df_death.columns.tolist()
            col_id = next((c for c in cols if c in ['attacker_steamid', 'attacker_xuid', 'attacker_steamid64']), None)
            
            if col_id and 'attacker_team_num' in df_death.columns:
                # Mostra uma amostra de jogadores e seus times
                amostra = df_death[[col_id, 'attacker_name', 'attacker_team_num']].drop_duplicates().head(10)
                st.dataframe(amostra, use_container_width=True)
            else:
                st.error("Não achei colunas de ID ou Time.")

    except Exception as e:
        st.error(f"Erro fatal: {e}")
    
    finally:
        os.remove(caminho)