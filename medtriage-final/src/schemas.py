from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal


class ClassificacaoSchema(BaseModel):
    """Schema de saída da Etapa 1 — classificação da solicitação médica."""

    tipo: Literal["emergencia", "consulta", "informacao"] = Field(
        description="Tipo da solicitação: emergencia (risco imediato de vida), "
                    "consulta (necessita avaliação médica) ou informacao (dúvida educativa)."
    )
    urgencia: Literal["alta", "media", "baixa"] = Field(
        description="Nível de urgência percebido: alta (ir agora), "
                    "media (dentro de 24h), baixa (pode aguardar)."
    )
    tema: str = Field(
        description="Tema médico identificado na solicitação. Ex: 'febre', 'dor torácica', 'nutrição'.",
        min_length=2,
        max_length=100,
    )

    @field_validator("tipo", mode="before")
    @classmethod
    def normalizar_tipo(cls, v):
        """Aceita variações comuns antes de validar o Literal."""
        mapa = {
            "emergência": "emergencia",
            "informação": "informacao",
        }
        return mapa.get(str(v).lower().strip(), str(v).lower().strip())

    @field_validator("urgencia", mode="before")
    @classmethod
    def normalizar_urgencia(cls, v):
        return str(v).lower().strip()


class ProcessamentoSchema(BaseModel):
    """Schema de saída da Etapa 2 — processamento condicional por tipo."""

    dados_extraidos: dict = Field(
        description="Dados estruturados extraídos da solicitação. "
                    "Varia por tipo: sintomas (emergencia/consulta) ou tópico (informacao)."
    )
    analise: str = Field(
        description="Análise textual da situação com base no tipo classificado.",
        min_length=10,
        max_length=1000,
    )
    sentimento: Optional[Literal["preocupado", "ansioso", "calmo", "neutro"]] = Field(
        default=None,
        description="Sentimento percebido na mensagem do usuário, quando identificável."
    )
    acao_recomendada: str = Field(
        description="Ação imediata recomendada com base na análise. "
                    "Ex: 'Ligar para o SAMU 192', 'Agendar consulta médica'."
    )


class RespostaSchema(BaseModel):
    """Schema de saída da Etapa 3 — resposta final formatada para o usuário."""

    resposta: str = Field(
        description="Texto da resposta educativa para o usuário. Tom empático e claro.",
        min_length=20,
        max_length=2000,
    )
    confianca: Literal["alta", "media", "baixa"] = Field(
        description="Nível de confiança da resposta: alta (sintomas claros e inequívocos), "
                    "media (sintomas ambíguos), baixa (informações insuficientes)."
    )
    acao_sugerida: str = Field(
        description="Ação concreta sugerida ao usuário ao final da resposta.",
        min_length=5,
        max_length=300,
    )
    disclaimer: str = Field(
        default="Esta orientação é educativa e não substitui avaliação médica profissional.",
        description="Aviso legal obrigatório ao final de toda resposta."
    )

    @field_validator("confianca", mode="before")
    @classmethod
    def normalizar_confianca(cls, v):
        return str(v).lower().strip()
