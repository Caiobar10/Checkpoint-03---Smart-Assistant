import os
import ollama


class LLMClient:
    """
    Cliente de comunicação com a Ollama API.
    Carrega o system prompt defensivo (camada 2 de guardrail) e o envia
    em todas as requisições ao modelo gpt-oss:120b.
    """

    def __init__(self):
        self.model = "gpt-oss:120b"
        self.system_prompt = self._carregar_system_prompt()

    def _carregar_system_prompt(self) -> str:
        """Carrega o system prompt defensivo do arquivo em prompts/system_prompt.txt."""
        caminho = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "system_prompt.txt"
        )
        caminho = os.path.normpath(caminho)
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            # Fallback minimo caso o arquivo nao exista
            return (
                "Você é um assistente de triagem médica. "
                "NUNCA dê diagnóstico. NUNCA receite medicamentos. "
                "SEMPRE recomende um profissional de saúde."
            )

    def gerar(self, prompt: str) -> str:
        """
        Envia o prompt ao LLM com o system prompt defensivo como contexto.
        Retorna o conteúdo textual da resposta.
        """
        resposta = ollama.chat(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self.system_prompt,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )
        return resposta["message"]["content"]
