"""
chain.py — Pipeline Multi-Etapa (Aula 09)

Implementa a classe AssistantChain com 3 etapas obrigatórias:
  Etapa 1: classificar  → ClassificacaoSchema  (tipo, urgência, tema)
  Etapa 2: processar    → ProcessamentoSchema  (condicional por tipo)
  Etapa 3: responder    → RespostaSchema       (resposta final formatada)

Cada etapa valida o JSON com Pydantic. Em caso de falha, tenta até
MAX_RETRIES vezes com um prompt de correção antes de aplicar fallback.
"""

import json
import re

from pydantic import ValidationError

from src.llm_client import LLMClient
from src.prompts import (
    prompt_classificacao,
    prompt_processamento,
    prompt_resposta,
)
from src.schemas import (
    ClassificacaoSchema,
    ProcessamentoSchema,
    RespostaSchema,
)

MAX_RETRIES = 2


def _extrair_json(texto: str) -> dict:
    """
    Tenta extrair JSON de uma string que pode conter texto ao redor.
    Estratégias:
    1. Parse direto
    2. Extração via regex de bloco entre chaves
    3. Extração de bloco de código markdown ```json ... ```
    """
    # Estratégia 1: parse direto
    try:
        return json.loads(texto.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    # Estratégia 2: bloco de código markdown
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # Estratégia 3: encontrar o primeiro objeto JSON completo
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass

    raise ValueError(f"Não foi possível extrair JSON válido da resposta: {texto[:200]}")


def _prompt_correcao(prompt_original: str, resposta_invalida: str, erro: str) -> str:
    """Gera um prompt de correção quando o LLM não retornou JSON válido."""
    return f"""
A sua última resposta não estava no formato JSON correto.
Erro encontrado: {erro}
Sua resposta anterior: {resposta_invalida[:300]}

Por favor, responda NOVAMENTE ao prompt abaixo, desta vez retornando
EXCLUSIVAMENTE um objeto JSON válido, sem texto adicional, sem markdown.

{prompt_original}
"""


class AssistantChain:
    """
    Pipeline de 3 etapas para processamento de solicitações médicas.

    Fluxo:
        Input → Etapa1 (classificar) → Etapa2 (processar, condicional) → Etapa3 (responder)
    """

    def __init__(self):
        self.llm = LLMClient()

    # ------------------------------------------------------------------
    # PIPELINE COMPLETO
    # ------------------------------------------------------------------

    def executar(self, texto: str) -> dict:
        """
        Executa o pipeline completo e retorna o dict da RespostaSchema.
        Propaga exceções se todas as tentativas falharem.
        """
        classificacao = self.etapa1_classificar(texto)
        processamento = self.etapa2_processar(classificacao, texto)
        resposta = self.etapa3_responder(processamento)
        return resposta

    # ------------------------------------------------------------------
    # ETAPA 1 — Classificação
    # ------------------------------------------------------------------

    def etapa1_classificar(self, texto: str) -> dict:
        """
        Classifica a solicitação em tipo, urgência e tema.
        Saída: ClassificacaoSchema validada.
        """
        prompt = prompt_classificacao(texto)
        return self._executar_com_retry(
            prompt=prompt,
            schema=ClassificacaoSchema,
            fallback={
                "tipo": "informacao",
                "urgencia": "baixa",
                "tema": "geral",
            },
            etapa="etapa1_classificar",
        )

    # ------------------------------------------------------------------
    # ETAPA 2 — Processamento condicional
    # ------------------------------------------------------------------

    def etapa2_processar(self, classificacao: dict, texto: str) -> dict:
        """
        Processa a solicitação de forma CONDICIONAL com base no tipo da Etapa 1:
          - emergencia  → extrai sintomas + sistema afetado + ação imediata
          - consulta    → extrai sintomas + especialidade + prazo
          - informacao  → extrai tópico + contexto + nível de resposta

        Esta lógica condicional é o diferencial do chain (não apenas sequencial).
        """
        tipo = classificacao.get("tipo", "informacao")
        prompt = prompt_processamento(classificacao, texto)

        fallback_por_tipo = {
            "emergencia": {
                "dados_extraidos": {"sintomas": [texto], "sistema_afetado": "não identificado", "tempo_inicio": "não informado"},
                "analise": "Possível situação de emergência. Avaliação imediata recomendada.",
                "sentimento": "preocupado",
                "acao_recomendada": "Ligar imediatamente para o SAMU (192) ou ir ao pronto-socorro.",
            },
            "consulta": {
                "dados_extraidos": {"sintomas": [texto], "duracao": "não informado", "especialidade_sugerida": "clínica geral"},
                "analise": "Situação que requer avaliação médica profissional.",
                "sentimento": "neutro",
                "acao_recomendada": "Agendar consulta médica o quanto antes.",
            },
            "informacao": {
                "dados_extraidos": {"topico": texto, "contexto": "geral", "nivel_resposta": "basico"},
                "analise": "Dúvida educativa sobre saúde.",
                "sentimento": "neutro",
                "acao_recomendada": "Consultar um profissional de saúde para mais informações.",
            },
        }

        return self._executar_com_retry(
            prompt=prompt,
            schema=ProcessamentoSchema,
            fallback=fallback_por_tipo.get(tipo, fallback_por_tipo["informacao"]),
            etapa="etapa2_processar",
        )

    # ------------------------------------------------------------------
    # ETAPA 3 — Resposta final
    # ------------------------------------------------------------------

    def etapa3_responder(self, processamento: dict) -> dict:
        """
        Gera a resposta final humanizada para o usuário.
        Usa Persona + CRISPE + Recipe Pattern (ver prompts.py).
        Saída: RespostaSchema validada.
        """
        prompt = prompt_resposta(processamento)
        return self._executar_com_retry(
            prompt=prompt,
            schema=RespostaSchema,
            fallback={
                "resposta": (
                    "Compreendo sua preocupação. Com base nas informações que você forneceu, "
                    "recomendo que você busque orientação de um profissional de saúde qualificado "
                    "para uma avaliação adequada da sua situação."
                ),
                "confianca": "baixa",
                "acao_sugerida": "Consulte um médico ou ligue para o SAMU (192) em caso de urgência.",
                "disclaimer": "Esta orientação é educativa e não substitui avaliação médica profissional.",
            },
            etapa="etapa3_responder",
        )

    # ------------------------------------------------------------------
    # HELPER — Execução com retry e fallback
    # ------------------------------------------------------------------

    def _executar_com_retry(
        self,
        prompt: str,
        schema,
        fallback: dict,
        etapa: str,
    ) -> dict:
        """
        Chama o LLM, tenta parsear e validar o JSON com o schema Pydantic.
        Em caso de falha, tenta novamente até MAX_RETRIES com prompt de correção.
        Se esgotar as tentativas, retorna o fallback sem lançar exceção.
        """
        ultimo_erro = ""
        ultima_resposta = ""
        prompt_atual = prompt

        for tentativa in range(1, MAX_RETRIES + 2):  # +2: tentativa inicial + retries
            try:
                ultima_resposta = self.llm.gerar(prompt_atual)
                dados = _extrair_json(ultima_resposta)
                validado = schema(**dados)
                return validado.model_dump()

            except (json.JSONDecodeError, ValueError) as e:
                ultimo_erro = f"JSON inválido: {e}"

            except ValidationError as e:
                ultimo_erro = f"Validação Pydantic falhou: {e.error_count()} erro(s)"
                # Tenta corrigir o JSON já extraído antes de retry
                try:
                    dados_parciais = _extrair_json(ultima_resposta)
                    # Aplica valores padrão para campos faltantes e tenta novamente
                    for chave, valor in fallback.items():
                        if chave not in dados_parciais:
                            dados_parciais[chave] = valor
                    validado = schema(**dados_parciais)
                    return validado.model_dump()
                except Exception:
                    pass

            except Exception as e:
                ultimo_erro = f"Erro inesperado na {etapa}: {e}"

            # Se não foi a última tentativa, gera prompt de correção
            if tentativa <= MAX_RETRIES:
                prompt_atual = _prompt_correcao(prompt, ultima_resposta, ultimo_erro)

        # Esgotou as tentativas — retorna fallback
        print(f"[AVISO] {etapa}: fallback ativado após {MAX_RETRIES + 1} tentativas. Último erro: {ultimo_erro}")
        return fallback
