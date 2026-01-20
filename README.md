# 🔫 CS2 Hub - Ranking & Estatísticas

![Status](https://img.shields.io/badge/Status-Active-success)
![Python](https://img.shields.io/badge/Python-3.10+-blue)
![CS2](https://img.shields.io/badge/Game-Counter--Strike%202-orange)

Uma aplicação web desenvolvida em **Streamlit** para processar demos de partidas competitivas de **Counter-Strike 2 (.dem)**, gerando um ranking automatizado entre amigos com estatísticas profissionais, análise de mapas e histórico de temporadas.

---

## 📸 Funcionalidades

* **📤 Upload e Processamento Automático:** Basta arrastar o arquivo `.dem`. O sistema detecta automaticamente o mapa, os jogadores, o placar e calcula todas as estatísticas (K/D, ADR, HS%, Utilitários).
* **🏆 Ranking Global:** Classificação geral dos jogadores com sistema de medalhas e pódio animado.
* **🧠 Rating Performance 2.0:** Um algoritmo de nota exclusivo que valoriza o trabalho em equipe (assistências e granadas) além das kills.
* **⚖️ Fator de Consistência:** Sistema anti-smurf que exige um número mínimo de partidas para atingir o ranking máximo.
* **🗺️ Estatísticas de Mapas:** Gráficos de Radar (Spider Chart) e Barras para analisar os pontos fortes e fracos do time em cada mapa (Mirage, Inferno, Nuke, etc.).
* **📜 Histórico e Admin:** Sistema para arquivar temporadas passadas e iniciar novos campeonatos.

---

## 🧮 Como Funciona o Ranking?

Para garantir uma competição justa e valorizar quem realmente ajuda o time, utilizamos duas métricas principais:

### 1. 🧠 O "Rating Performance" (Sua Nota de Habilidade)
Diferente do K/D simples, nossa fórmula recompensa o uso de utilitários e o trabalho em equipe.

$$
\text{Rating} = \frac{\text{Kills} + (\text{Assists} \times 0.4) + (\text{Cegos} \times 0.2) + (\text{DanoUtil} \div 100)}{\text{Mortes}}
$$

**O que isso significa?**
* 🔫 **Kills:** Valem 1.0 ponto.
* 🤝 **Assistências:** Valem 0.4 de uma kill (quem ajuda, pontua!).
* 💡 **Inimigos Cegos (Flash):** Valem 0.2 de uma kill.
* 💣 **Dano de Utilitário:** Cada 100 de dano causado com granadas/molotov vale 1.0 kill.
* 💀 **Mortes:** São o divisor. Quanto mais você morre, mais difícil manter o rating alto.

### 2. ⚖️ O Fator de Consistência (A Regra dos 50 Jogos)
Para evitar que um jogador jogue apenas uma partida, dê sorte e fique em 1º lugar para sempre, aplicamos uma penalidade proporcional até que ele prove sua regularidade.

$$
\text{Rating Oficial} = \text{Rating Base} \times \min\left(1, \frac{\text{Jogos Jogados}}{50}\right)
$$

**Tabela de Impacto:**

| Partidas Jogadas | Peso da Nota | Situação |
| :--- | :--- | :--- |
| 🐣 **10 Jogos** | 20% | Nota reduzida (Iniciante na season) |
| 🐥 **25 Jogos** | 50% | Nota parcial (Ganhando experiência) |
| 🦅 **50 Jogos** | **100%** | **Nota Real (Lenda do Ranking)** |
| 🐉 **100+ Jogos** | **100%** | **Nota Real** (Máximo de 100%) |

> **Resumo:** Você precisa jogar pelo menos **50 partidas** para que seu Rating seja contabilizado integralmente.

**Philipy Macêdo** -> Engenharia de Sistemas e Computação - UERJ
