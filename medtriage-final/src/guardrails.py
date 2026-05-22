"""
guardrails.py — Sistema de Guardrails de 3 Camadas (Aula 10)

Camada 1 — Input Guard:   valida tamanho, caracteres proibidos e 10+ padrões de injection
Camada 2 — System Prompt: carregado no LLMClient e enviado a cada requisição (ver llm_client.py)
Camada 3 — Output Guard:  verifica JSON válido, domínio médico e ausência de vazamentos
"""

import re
import json


class GuardrailSystem:
    """
    Sistema completo de guardrails para o MedTriage Bot.

    Uso:
        guard = GuardrailSystem()
        seguro, motivo = guard.validar_input(texto_usuario)
        seguro, motivo = guard.validar_output(resposta_llm)
    """

    # ------------------------------------------------------------------
    # PADRÕES DE PROMPT INJECTION (Camada 1)
    # ------------------------------------------------------------------

    PADROES_INJECTION = [
        # Padrões clássicos de jailbreak
        r"ignore\s+(all\s+)?instructions?",
        r"forget\s+(all\s+)?(your\s+)?rules?",
        r"reveal\s+(your\s+)?(system\s+)?prompt",
        r"\bdan\s*mode\b",
        r"\bjailbreak\b",
        # Instruções de override
        r"(ignore|skip|bypass|override)\s+(the\s+)?(above|previous|prior|all)\s+(instructions?|rules?|constraints?|guidelines?)",
        r"new\s+(instructions?|rules?|prompt|persona|mode)",
        r"act\s+as\s+(if\s+)?(you\s+)?(are|were|have\s+no)",
        r"pretend\s+(you\s+)?(are|have|don'?t)",
        # Tentativas de extração de prompt
        r"(print|show|display|repeat|output|write)\s+(your\s+)?(system|initial|original|full)\s+prompt",
        r"what\s+(are|were)\s+your\s+instructions?",
        r"reveal\s+your\s+(persona|identity|rules?|constraints?)",
        # Variantes em português
        r"ignore\s+as\s+instru[cç][oõ]es",
        r"esque[cç]a\s+(as\s+)?(suas\s+)?regras",
        r"mostre?\s+(o\s+)?(seu\s+)?(prompt|system)",
        r"finja\s+que\s+(você\s+)?(é|não\s+tem)",
        r"(novo|nova)\s+(prompt|persona|modo|instrução|instrucao)",
        r"ignore\s+(tudo|todas)\s+acima",
    ]

    # Termos que NÃO devem aparecer na saída (vazamento de system prompt)
    TERMOS_VAZAMENTO = [
        "system prompt",
        "ignore instructions",
        "regras_absolutas",
        "reforco_critico",
        "<sistema>",
        "<persona>",
        "<regras",
        "você é a dr. ana",
        "15 anos de experiência em enfermagem",
        "instrucoes internas",
        "estas regras nunca podem",
    ]

    # Termos fora do domínio médico que NÃO devem aparecer nas respostas
    TERMOS_FORA_DOMINIO = [
        "código python",
        "script javascript",
        "como hackear",
        "receita de bolo",
        "cotação do dólar",
        "resultado do jogo",
    ]

    # Palavras-chave médicas mínimas esperadas em respostas legítimas
    PALAVRAS_DOMINIO_MEDICO = [
        "saúde", "médico", "médica", "sintoma", "consulta", "profissional",
        "samu", "pronto-socorro", "hospital", "clínica", "orientação",
        "paciente", "tratamento", "avaliação", "enfermagem", "dr.", "dra.",
    ]

    def __init__(self):
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE | re.UNICODE)
            for p in self.PADROES_INJECTION
        ]

    # ------------------------------------------------------------------
    # CAMADA 1 — Input Guard
    # ------------------------------------------------------------------

    def validar_input(self, texto: str) -> tuple[bool, str]:
        """
        Valida o input do usuário antes de enviá-lo ao pipeline.

        Verifica:
        - Tamanho máximo (500 caracteres)
        - Caracteres HTML/JSON proibidos (<, >, {, })
        - 18+ padrões regex de prompt injection

        Retorna (is_safe: bool, motivo: str)
        """
        # Verificação 1: tamanho
        if not texto or not texto.strip():
            return False, "Entrada vazia."

        if len(texto) > 500:
            return False, f"Texto muito longo ({len(texto)} caracteres). Máximo: 500."

        # Verificação 2: caracteres proibidos
        chars_proibidos = {"<", ">", "{", "}", "\\", "`"}
        encontrados = [c for c in chars_proibidos if c in texto]
        if encontrados:
            return False, f"Caracteres não permitidos detectados: {', '.join(encontrados)}"

        # Verificação 3: padrões de prompt injection
        texto_normalizado = texto.lower().strip()
        for pattern in self._compiled_patterns:
            if pattern.search(texto_normalizado):
                return False, f"Tentativa de manipulação do assistente detectada e bloqueada."

        return True, "OK"

    # ------------------------------------------------------------------
    # CAMADA 3 — Output Guard
    # ------------------------------------------------------------------

    def validar_output(self, resposta) -> tuple[bool, str]:
        """
        Valida a saída do LLM antes de exibi-la ao usuário.

        Verifica:
        - JSON válido (quando aplicável)
        - Ausência de vazamento do system prompt
        - Resposta dentro do domínio médico

        Retorna (is_safe: bool, motivo: str)
        """
        resposta_str = str(resposta).lower()

        # Verificação 1: vazamento de system prompt
        for termo in self.TERMOS_VAZAMENTO:
            if termo.lower() in resposta_str:
                return False, f"Possível vazamento de instrução interna detectado. Resposta bloqueada."

        # Verificação 2: conteúdo fora do domínio
        for termo in self.TERMOS_FORA_DOMINIO:
            if termo.lower() in resposta_str:
                return False, f"Resposta fora do domínio médico detectada. Bloqueada."

        # Verificação 3: se for dict/RespostaSchema, checar campo 'resposta'
        if isinstance(resposta, dict):
            texto_resposta = resposta.get("resposta", "")
            if texto_resposta:
                # Verifica se tem ao menos uma palavra do domínio médico
                tem_dominio = any(
                    palavra in texto_resposta.lower()
                    for palavra in self.PALAVRAS_DOMINIO_MEDICO
                )
                if not tem_dominio and len(texto_resposta) > 50:
                    return False, "Resposta não parece estar dentro do domínio médico."

        return True, "OK"

    def validar_json_output(self, texto: str) -> tuple[bool, str]:
        """
        Verifica se um texto é JSON válido.
        Usado pelo evaluator para calcular a métrica 'taxa de JSON válido'.
        """
        try:
            json.loads(texto)
            return True, "JSON válido"
        except (json.JSONDecodeError, ValueError) as e:
            return False, f"JSON inválido: {str(e)}"
