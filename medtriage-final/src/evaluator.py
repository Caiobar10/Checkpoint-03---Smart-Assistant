"""
evaluator.py — Avaliação Automática do MedTriage Bot (Aula 09)

Carrega test_dataset.json e attack_dataset.json, executa o pipeline
completo e calcula 5 métricas:

  1. Acurácia de classificação  — % de tipos classificados corretamente (Etapa 1)
  2. Taxa de JSON válido        — % de respostas que passaram na validação Pydantic
  3. Taxa de bloqueio           — % de ataques corretamente bloqueados pelos guardrails
  4. Taxa de falso positivo     — % de solicitações legítimas bloqueadas incorretamente
  5. Consistência               — mesma solicitação 3x → mesma classificação?

Gera:
  - output/eval_results.csv    (resultados detalhados)
  - output/graficos/           (5 gráficos: barras, pizza, radar, heatmap, linha)
"""

import json
import os
import sys

import pandas as pd
import matplotlib
matplotlib.use("Agg")  # backend sem GUI para ambientes sem display
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from src.chain import AssistantChain
from src.guardrails import GuardrailSystem


OUTPUT_DIR = "output"
GRAFICOS_DIR = os.path.join(OUTPUT_DIR, "graficos")
CSV_PATH = os.path.join(OUTPUT_DIR, "eval_results.csv")


def _garantir_diretorios():
    os.makedirs(GRAFICOS_DIR, exist_ok=True)


def _carregar_json(caminho: str) -> list:
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# AVALIAÇÃO DE CASOS LEGÍTIMOS
# ---------------------------------------------------------------------------

def avaliar_casos_legitimos(chain: AssistantChain, guard: GuardrailSystem, casos: list) -> pd.DataFrame:
    """Executa o pipeline em cada caso legítimo e coleta resultados."""
    resultados = []

    for caso in casos:
        caso_id = caso.get("id", "?")
        texto = caso["texto"]
        tipo_esperado = caso["tipo_esperado"]
        palavras_chave = caso.get("palavras_chave_resposta", [])

        resultado = {
            "id": caso_id,
            "texto": texto,
            "tipo_esperado": tipo_esperado,
            "tipo_obtido": None,
            "acerto_classificacao": False,
            "json_valido_etapa1": False,
            "json_valido_etapa3": False,
            "bloqueado_indevido": False,
            "palavras_chave_presentes": False,
            "erro": None,
        }

        try:
            # Verifica se foi bloqueado indevidamente pelo input guard
            seguro, motivo = guard.validar_input(texto)
            if not seguro:
                resultado["bloqueado_indevido"] = True
                resultado["erro"] = f"Falso positivo: {motivo}"
                resultados.append(resultado)
                continue

            # Etapa 1 — classificação
            try:
                etapa1 = chain.etapa1_classificar(texto)
                resultado["json_valido_etapa1"] = True
                resultado["tipo_obtido"] = etapa1.get("tipo")
                resultado["acerto_classificacao"] = (
                    etapa1.get("tipo") == tipo_esperado
                )

                # Etapa 2 e 3
                try:
                    etapa2 = chain.etapa2_processar(etapa1, texto)
                    etapa3 = chain.etapa3_responder(etapa2)
                    resultado["json_valido_etapa3"] = True

                    # Verifica palavras-chave na resposta final
                    resposta_texto = str(etapa3.get("resposta", "")).lower()
                    resultado["palavras_chave_presentes"] = any(
                        p.lower() in resposta_texto for p in palavras_chave
                    )

                    # Output guard
                    seguro_out, _ = guard.validar_output(etapa3)
                    if not seguro_out:
                        resultado["erro"] = "Output guard bloqueou a resposta"

                except Exception as e:
                    resultado["erro"] = f"Etapas 2/3 falharam: {e}"

            except Exception as e:
                resultado["erro"] = f"Etapa 1 falhou: {e}"

        except Exception as e:
            resultado["erro"] = f"Erro geral: {e}"

        resultados.append(resultado)

    return pd.DataFrame(resultados)


# ---------------------------------------------------------------------------
# AVALIAÇÃO DE ATAQUES
# ---------------------------------------------------------------------------

def avaliar_ataques(guard: GuardrailSystem, ataques: list) -> pd.DataFrame:
    """Testa se o input guard bloqueia corretamente cada ataque."""
    resultados = []

    for ataque in ataques:
        texto = ataque["texto"]
        tipo_ataque = ataque.get("tipo_ataque", "desconhecido")
        descricao = ataque.get("descricao", "")

        seguro, motivo = guard.validar_input(texto)

        resultados.append({
            "id": ataque.get("id", "?"),
            "tipo_ataque": tipo_ataque,
            "descricao": descricao,
            "texto": texto[:80] + "..." if len(texto) > 80 else texto,
            "bloqueado": not seguro,
            "motivo": motivo,
            "correto": not seguro,  # esperado sempre BLOQUEADO
        })

    return pd.DataFrame(resultados)


# ---------------------------------------------------------------------------
# TESTE DE CONSISTÊNCIA
# ---------------------------------------------------------------------------

def avaliar_consistencia(chain: AssistantChain, guard: GuardrailSystem, casos: list, n_repeticoes: int = 3) -> pd.DataFrame:
    """
    Executa 3 solicitações idênticas e verifica se a classificação é consistente.
    Usa os 5 primeiros casos do dataset.
    """
    amostras = casos[:5]
    resultados = []

    for caso in amostras:
        texto = caso["texto"]
        seguro, _ = guard.validar_input(texto)
        if not seguro:
            continue

        tipos_obtidos = []
        for _ in range(n_repeticoes):
            try:
                etapa1 = chain.etapa1_classificar(texto)
                tipos_obtidos.append(etapa1.get("tipo", "erro"))
            except Exception:
                tipos_obtidos.append("erro")

        consistente = len(set(tipos_obtidos)) == 1

        resultados.append({
            "texto": texto[:60] + "..." if len(texto) > 60 else texto,
            "tipo_esperado": caso["tipo_esperado"],
            "tipos_obtidos": ", ".join(tipos_obtidos),
            "consistente": consistente,
        })

    return pd.DataFrame(resultados)


# ---------------------------------------------------------------------------
# CÁLCULO DAS 5 MÉTRICAS
# ---------------------------------------------------------------------------

def calcular_metricas(df_legitimos: pd.DataFrame, df_ataques: pd.DataFrame, df_consistencia: pd.DataFrame) -> dict:
    total = len(df_legitimos)
    total_ataques = len(df_ataques)

    acuracia = df_legitimos["acerto_classificacao"].mean() * 100 if total > 0 else 0
    taxa_json = (
        (df_legitimos["json_valido_etapa1"].sum() + df_legitimos["json_valido_etapa3"].sum())
        / (total * 2) * 100 if total > 0 else 0
    )
    taxa_bloqueio = df_ataques["bloqueado"].mean() * 100 if total_ataques > 0 else 0
    taxa_fp = df_legitimos["bloqueado_indevido"].mean() * 100 if total > 0 else 0
    consistencia = df_consistencia["consistente"].mean() * 100 if len(df_consistencia) > 0 else 0

    return {
        "1_acuracia_classificacao_%": round(acuracia, 1),
        "2_taxa_json_valido_%": round(taxa_json, 1),
        "3_taxa_bloqueio_ataques_%": round(taxa_bloqueio, 1),
        "4_taxa_falso_positivo_%": round(taxa_fp, 1),
        "5_consistencia_%": round(consistencia, 1),
    }


# ---------------------------------------------------------------------------
# GERAÇÃO DE GRÁFICOS
# ---------------------------------------------------------------------------

def gerar_graficos(metricas: dict, df_legitimos: pd.DataFrame, df_ataques: pd.DataFrame, df_consistencia: pd.DataFrame):
    plt.rcParams.update({
        "figure.dpi": 120,
        "font.family": "DejaVu Sans",
        "axes.spines.top": False,
        "axes.spines.right": False,
    })

    cores = ["#4A90D9", "#5CB85C", "#F0AD4E", "#D9534F", "#9B59B6"]

    # --- Gráfico 1: Barras — 5 métricas ---
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = [k.replace("_", " ").replace("%", "").strip() for k in metricas.keys()]
    valores = list(metricas.values())
    barras = ax.bar(labels, valores, color=cores, width=0.6, edgecolor="white")
    ax.set_ylim(0, 110)
    ax.set_ylabel("Valor (%)")
    ax.set_title("MedTriage Bot — 5 Métricas de Avaliação", fontsize=13, fontweight="bold", pad=15)
    for barra, val in zip(barras, valores):
        ax.text(barra.get_x() + barra.get_width() / 2, barra.get_height() + 1.5,
                f"{val:.1f}%", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.axhline(y=80, color="gray", linestyle="--", linewidth=0.8, alpha=0.6, label="Meta mínima 80%")
    ax.legend(fontsize=9)
    plt.xticks(rotation=20, ha="right", fontsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(GRAFICOS_DIR, "01_metricas_gerais.png"), bbox_inches="tight")
    plt.close()

    # --- Gráfico 2: Pizza — distribuição de tipos classificados ---
    if "tipo_obtido" in df_legitimos.columns and not df_legitimos["tipo_obtido"].dropna().empty:
        contagem = df_legitimos["tipo_obtido"].value_counts()
        fig, ax = plt.subplots(figsize=(6, 5))
        wedges, texts, autotexts = ax.pie(
            contagem.values, labels=contagem.index,
            autopct="%1.0f%%", colors=["#D9534F", "#4A90D9", "#5CB85C"],
            startangle=90, pctdistance=0.75
        )
        ax.set_title("Distribuição de Tipos Classificados", fontsize=12, fontweight="bold")
        plt.tight_layout()
        plt.savefig(os.path.join(GRAFICOS_DIR, "02_distribuicao_tipos.png"), bbox_inches="tight")
        plt.close()

    # --- Gráfico 3: Radar — métricas em radar chart ---
    categorias = ["Acurácia", "JSON Válido", "Bloqueio", "Sem FP", "Consistência"]
    valores_radar = [
        metricas["1_acuracia_classificacao_%"],
        metricas["2_taxa_json_valido_%"],
        metricas["3_taxa_bloqueio_ataques_%"],
        100 - metricas["4_taxa_falso_positivo_%"],  # inverter FP
        metricas["5_consistencia_%"],
    ]
    N = len(categorias)
    angulos = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    valores_radar += valores_radar[:1]
    angulos += angulos[:1]

    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
    ax.plot(angulos, valores_radar, "o-", linewidth=2, color="#4A90D9")
    ax.fill(angulos, valores_radar, alpha=0.25, color="#4A90D9")
    ax.set_xticks(angulos[:-1])
    ax.set_xticklabels(categorias, fontsize=10)
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20%", "40%", "60%", "80%", "100%"], fontsize=8)
    ax.set_title("Radar de Desempenho — MedTriage Bot", fontsize=12, fontweight="bold", pad=20)
    plt.tight_layout()
    plt.savefig(os.path.join(GRAFICOS_DIR, "03_radar_desempenho.png"), bbox_inches="tight")
    plt.close()

    # --- Gráfico 4: Heatmap — acerto por tipo de classificação ---
    if "tipo_esperado" in df_legitimos.columns and "tipo_obtido" in df_legitimos.columns:
        tipos = ["emergencia", "consulta", "informacao"]
        matriz = np.zeros((len(tipos), len(tipos)), dtype=int)
        for _, row in df_legitimos.dropna(subset=["tipo_esperado", "tipo_obtido"]).iterrows():
            esp = row["tipo_esperado"]
            obt = row["tipo_obtido"]
            if esp in tipos and obt in tipos:
                matriz[tipos.index(esp)][tipos.index(obt)] += 1

        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(matriz, cmap="Blues")
        ax.set_xticks(range(len(tipos)))
        ax.set_yticks(range(len(tipos)))
        ax.set_xticklabels([t.capitalize() for t in tipos])
        ax.set_yticklabels([t.capitalize() for t in tipos])
        ax.set_xlabel("Tipo Obtido")
        ax.set_ylabel("Tipo Esperado")
        ax.set_title("Matriz de Confusão — Classificação", fontsize=12, fontweight="bold")
        for i in range(len(tipos)):
            for j in range(len(tipos)):
                ax.text(j, i, str(matriz[i][j]), ha="center", va="center",
                        fontsize=13, fontweight="bold",
                        color="white" if matriz[i][j] > matriz.max() * 0.5 else "black")
        plt.colorbar(im, ax=ax, shrink=0.8)
        plt.tight_layout()
        plt.savefig(os.path.join(GRAFICOS_DIR, "04_matriz_confusao.png"), bbox_inches="tight")
        plt.close()

    # --- Gráfico 5: Barras horizontais — ataques bloqueados vs passaram ---
    if len(df_ataques) > 0:
        bloqueados = df_ataques["bloqueado"].sum()
        passaram = len(df_ataques) - bloqueados
        categorias_ataque = df_ataques["tipo_ataque"].tolist()
        valores_bloqueio = df_ataques["bloqueado"].astype(int).tolist()

        fig, ax = plt.subplots(figsize=(9, max(4, len(df_ataques) * 0.5)))
        cores_bloqueio = ["#5CB85C" if v else "#D9534F" for v in valores_bloqueio]
        barras_h = ax.barh(categorias_ataque, valores_bloqueio, color=cores_bloqueio, edgecolor="white")
        ax.set_xlim(0, 1.3)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Passou", "Bloqueado"])
        ax.set_title("Resultado por Tipo de Ataque", fontsize=12, fontweight="bold")
        for barra, val in zip(barras_h, valores_bloqueio):
            label = "✓ BLOQUEADO" if val else "✗ PASSOU"
            ax.text(val + 0.02, barra.get_y() + barra.get_height() / 2,
                    label, va="center", fontsize=9, fontweight="bold")
        verde = mpatches.Patch(color="#5CB85C", label="Bloqueado (correto)")
        vermelho = mpatches.Patch(color="#D9534F", label="Passou (falha)")
        ax.legend(handles=[verde, vermelho], fontsize=9)
        plt.tight_layout()
        plt.savefig(os.path.join(GRAFICOS_DIR, "05_ataques_bloqueados.png"), bbox_inches="tight")
        plt.close()

    print(f"[OK] 5 gráficos salvos em {GRAFICOS_DIR}/")


# ---------------------------------------------------------------------------
# PONTO DE ENTRADA
# ---------------------------------------------------------------------------

def rodar_avaliacao():
    """Executa a avaliação completa e gera relatório + gráficos."""
    _garantir_diretorios()

    print("\n" + "=" * 60)
    print("  MedTriage Bot — Avaliação Automática")
    print("=" * 60)

    chain = AssistantChain()
    guard = GuardrailSystem()

    # Carrega datasets
    casos = _carregar_json(os.path.join("data", "test_dataset.json"))
    ataques = _carregar_json(os.path.join("data", "attack_dataset.json"))

    print(f"\n[1/4] Avaliando {len(casos)} casos legítimos...")
    df_legitimos = avaliar_casos_legitimos(chain, guard, casos)

    print(f"[2/4] Testando {len(ataques)} ataques de injection...")
    df_ataques = avaliar_ataques(guard, ataques)

    print("[3/4] Testando consistência (3 repetições × 5 amostras)...")
    df_consistencia = avaliar_consistencia(chain, guard, casos)

    # Calcula métricas
    metricas = calcular_metricas(df_legitimos, df_ataques, df_consistencia)

    print("\n" + "=" * 60)
    print("  MÉTRICAS DE AVALIAÇÃO")
    print("=" * 60)
    for nome, valor in metricas.items():
        label = nome.replace("_", " ").replace("%", "").strip()
        print(f"  {label:<35} {valor:>6.1f}%")

    # Análise de erros
    erros = df_legitimos[df_legitimos["erro"].notna()]
    if not erros.empty:
        print(f"\n  Casos com erro: {len(erros)}")
        for _, row in erros.iterrows():
            print(f"    [{row['id']}] {row['erro']}")

    print("=" * 60)

    # Salva CSV consolidado
    df_legitimos.to_csv(CSV_PATH, index=False, encoding="utf-8")
    print(f"\n[OK] Resultados salvos em {CSV_PATH}")

    # Gera gráficos
    print("[4/4] Gerando gráficos...")
    gerar_graficos(metricas, df_legitimos, df_ataques, df_consistencia)

    return metricas


if __name__ == "__main__":
    rodar_avaliacao()
