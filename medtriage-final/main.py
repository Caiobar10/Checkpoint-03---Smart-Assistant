"""
main.py — Ponto de entrada do MedTriage Bot (Aula 09 / 10)

Modo 1 (padrão): python main.py
  → Conversa interativa com o assistente de triagem médica

Modo 2: python main.py --avaliar
  → Executa a avaliação automática com os datasets de teste e gera relatório
"""

import sys
import json

from src.guardrails import GuardrailSystem
from src.chain import AssistantChain


BANNER = """
╔══════════════════════════════════════════════════════╗
║          MedTriage Bot — Assistente de Triagem       ║
║          FIAP · CP03 · Prompt Engineering & AI       ║
╚══════════════════════════════════════════════════════╝
  Dr. Ana está pronta para orientar você.
  Digite 'sair' para encerrar | '--avaliar' para rodar avaliação
"""


def modo_interativo():
    """
    Modo 1 — Conversa interativa.

    Pipeline por mensagem:
      Input → Input Guard → Etapa1 (classificar) → Etapa2 (processar)
           → Etapa3 (responder) → Output Guard → Exibe resposta
    """
    guard = GuardrailSystem()
    chain = AssistantChain()

    print(BANNER)

    while True:
        try:
            texto = input("\nVocê: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nAté logo! Cuide-se.")
            break

        if not texto:
            continue

        if texto.lower() in ("sair", "exit", "quit"):
            print("Até logo! Cuide-se.")
            break

        if texto.lower() == "--avaliar":
            modo_avaliacao()
            continue

        # --- Camada 1: Input Guard ---
        seguro, motivo = guard.validar_input(texto)
        if not seguro:
            print(f"\n🔒 Dr. Ana: Não foi possível processar essa mensagem. [{motivo}]")
            continue

        print("\nDr. Ana: Analisando sua solicitação...\n")

        try:
            # --- Chain de 3 Etapas ---
            resposta = chain.executar(texto)

            # --- Camada 3: Output Guard ---
            seguro_saida, motivo_saida = guard.validar_output(resposta)
            if not seguro_saida:
                print(f"🔒 Dr. Ana: Não consigo fornecer essa resposta no momento. [{motivo_saida}]")
                continue

            # Exibe resposta formatada
            _exibir_resposta(resposta)

        except Exception as e:
            print(f"Dr. Ana: Ocorreu um erro ao processar sua solicitação. Por favor, tente novamente.")
            print(f"  (Detalhes técnicos: {e})")


def modo_avaliacao():
    """
    Modo 2 — Avaliação automática com datasets de teste e ataques.
    Gera eval_results.csv e gráficos em output/graficos/.
    """
    print("\n[Modo Avaliação] Carregando pipeline de testes...\n")
    from src.evaluator import rodar_avaliacao
    rodar_avaliacao()


def _exibir_resposta(resposta: dict):
    """Formata e exibe a resposta final para o usuário."""
    print("─" * 56)
    print(resposta.get("resposta", ""))
    print()

    confianca = resposta.get("confianca", "")
    icone_confianca = {"alta": "🟢", "media": "🟡", "baixa": "🔴"}.get(confianca, "⚪")

    print(f"  Ação sugerida: {resposta.get('acao_sugerida', '')}")
    print(f"  Confiança da orientação: {icone_confianca} {confianca.capitalize()}")
    print()
    print(f"  ⚠️  {resposta.get('disclaimer', 'Esta orientação é educativa e não substitui avaliação médica profissional.')}")
    print("─" * 56)


if __name__ == "__main__":
    if "--avaliar" in sys.argv:
        modo_avaliacao()
    else:
        modo_interativo()
