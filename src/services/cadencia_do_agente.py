"""De quanto em quanto tempo corre um agente — num sítio só.

> «Correr agora não existe, e as frequências são grosseiras.» — Lucas, 10/10/2026

── Porque é que isto existe ─────────────────────────────────────────────────

A cadência de um agente era decidida em TRÊS sítios, e cada um lia coisas
diferentes:

* `agent_service._compute_next_execution` — na criação e no retomar. Lia a
  `frequency` e multiplicava pelo `interval_value`, ignorando a unidade.
* `agent_worker.next_run_at` — depois de cada corrida. Lia só a `frequency`,
  com uma tabela SEM `minutely`: um agente «de 5 em 5 minutos» corria a
  primeira vez daí a 5 minutos e, a partir daí, uma vez por DIA.
* `limites_do_plano.intervalo_em_minutos` — o portão do plano. Lia a unidade
  mas não conhecia `minutely`, e por isso um agente `minutely` sem unidade
  passava o portão de qualquer plano.

Três respostas para a mesma pergunta. Agora há uma.

── O que o `schedule_jsonb` aceita ──────────────────────────────────────────

    {"interval_value": 15, "interval_unit": "minute"}        de 15 em 15 min
    {"interval_value": 2,  "interval_unit": "day",
     "hour": 8, "minute": 30, "timezone": "Europe/Madrid"}   dia sim dia não, 08:30
    {"weekdays": [0, 2, 4], "hour": 9, "minute": 0,
     "timezone": "Europe/Madrid"}                            seg/qua/sex às 09:00

`weekdays` usa 0 = segunda … 6 = domingo (o `datetime.weekday()` do Python), e
aceita também os nomes curtos em inglês (`mon`, `tue`, …). A hora pode vir como
`hour`/`minute` ou como `time: "HH:MM"` — a web grava a segunda forma, e até
hoje era ignorada.

Sem `timezone`, a hora é UTC: é o que sempre foi, e um agente gravado antes
desta mudança tem de continuar a correr à mesma hora.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: Minutos por unidade.
UNIDADE_MIN: Dict[str, int] = {"minute": 1, "hour": 60, "day": 1440, "week": 10080}

#: Minutos por frequência antiga. `once` e `manual` não têm cadência.
FREQUENCIA_MIN: Dict[str, int] = {
    "minutely": 1,
    "hourly": 60,
    "daily": 1440,
    "weekly": 10080,
    "monthly": 43200,
    "realtime": 1,
    "continuous": 1,
}

SEM_CADENCIA = ("once", "manual")

_NOMES_DOS_DIAS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

#: Hora por omissão de um agente «em dias da semana» sem hora escolhida.
HORA_POR_OMISSAO = 9


class CadenciaInvalida(ValueError):
    """Um `schedule_jsonb` que não se consegue ler. Vira 422 na API."""


# ── Ler ──────────────────────────────────────────────────────────────────


def _dias(cfg: Dict[str, Any]) -> List[int]:
    bruto = cfg.get("weekdays")
    if not bruto:
        return []
    if not isinstance(bruto, (list, tuple)):
        raise CadenciaInvalida("weekdays tem de ser uma lista")
    dias: set[int] = set()
    for d in bruto:
        if isinstance(d, str) and d.strip().lower()[:3] in _NOMES_DOS_DIAS:
            dias.add(_NOMES_DOS_DIAS.index(d.strip().lower()[:3]))
            continue
        try:
            n = int(d)
        except (TypeError, ValueError):
            raise CadenciaInvalida(f"dia da semana desconhecido: {d!r}")
        if not 0 <= n <= 6:
            raise CadenciaInvalida(f"dia da semana fora de 0..6: {d!r}")
        dias.add(n)
    return sorted(dias)


def hora_escolhida(cfg: Any) -> Tuple[Optional[int], int]:
    """A hora escolhida, se houver: `(hora, minuto)` ou `(None, 0)`.

    Tolerante de propósito — um blob estragado não pode parar o agendador.
    """
    if not isinstance(cfg, dict):
        return None, 0
    hora = cfg.get("hour")
    minuto = cfg.get("minute")
    tempo = cfg.get("time")
    if hora is None and isinstance(tempo, str) and ":" in tempo:
        # «08:30» ou «08:30 UTC» — a web grava assim.
        partes = tempo.strip().split()[0].split(":")
        hora, minuto = partes[0], partes[1] if len(partes) > 1 else 0
    if hora is None:
        return None, 0
    try:
        h = max(0, min(23, int(hora)))
        m = max(0, min(59, int(minuto or 0)))
    except (TypeError, ValueError):
        return None, 0
    return h, m


def _fuso(cfg: Dict[str, Any]) -> ZoneInfo | timezone:
    nome = cfg.get("timezone") if isinstance(cfg, dict) else None
    if not nome:
        return timezone.utc
    try:
        return ZoneInfo(str(nome))
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def normalizar(cfg: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Valida e limpa o que chega da API. Levanta `CadenciaInvalida`.

    Só se usa à ESCRITA. À leitura o agendador é tolerante, porque um agente
    gravado com um blob estranho tem de continuar a correr.
    """
    if cfg is None:
        return None
    if not isinstance(cfg, dict):
        raise CadenciaInvalida("schedule_jsonb tem de ser um objecto")
    limpo: Dict[str, Any] = dict(cfg)
    dias = _dias(cfg)
    if dias:
        limpo["weekdays"] = dias
    else:
        limpo.pop("weekdays", None)
    if cfg.get("interval_value") is not None:
        try:
            v = int(cfg["interval_value"])
        except (TypeError, ValueError):
            raise CadenciaInvalida("interval_value tem de ser um número inteiro")
        if v < 1:
            raise CadenciaInvalida("interval_value tem de ser pelo menos 1")
        limpo["interval_value"] = v
    unidade = cfg.get("interval_unit")
    if unidade is not None and unidade not in UNIDADE_MIN and unidade != "month":
        raise CadenciaInvalida(f"interval_unit desconhecida: {unidade!r}")
    if cfg.get("timezone"):
        try:
            ZoneInfo(str(cfg["timezone"]))
        except (ZoneInfoNotFoundError, ValueError):
            raise CadenciaInvalida(f"fuso horário desconhecido: {cfg['timezone']!r}")
    h, m = hora_escolhida(cfg)
    if (cfg.get("hour") is not None or cfg.get("time")) and h is None:
        raise CadenciaInvalida("hora ilegível")
    return limpo


def intervalo_em_minutos(
    cfg: Optional[Dict[str, Any]], frequency: Optional[str] = None
) -> Optional[int]:
    """O intervalo MAIS CURTO entre duas corridas, em minutos.

    É o número que o plano compara com o seu mínimo. Para dias da semana é a
    menor distância entre dois dias escolhidos (seg+ter = 1 dia; só à
    segunda = 7 dias). `None` quando o agente não tem cadência (manual).
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    try:
        dias = _dias(cfg)
    except CadenciaInvalida:
        dias = []
    if dias:
        if len(dias) == 1:
            return 7 * 1440
        distancias = [b - a for a, b in zip(dias, dias[1:])] + [dias[0] + 7 - dias[-1]]
        return min(distancias) * 1440

    valor = cfg.get("interval_value")
    unidade = cfg.get("interval_unit")
    try:
        valor = int(valor) if valor is not None else None
    except (TypeError, ValueError):
        valor = None
    if unidade == "month":
        return (valor or 1) * 43200
    if valor and unidade in UNIDADE_MIN:
        return valor * UNIDADE_MIN[unidade]

    base = FREQUENCIA_MIN.get(str(frequency or "").lower())
    if base is None:
        return None
    # `interval_value` sem unidade multiplica a frequência — era assim que o
    # `_compute_next_execution` o lia, e há agentes gravados dessa maneira.
    return base * (valor if valor and valor > 1 else 1)


def _tem_cadencia_propria(cfg: Any) -> bool:
    if not isinstance(cfg, dict):
        return False
    try:
        if _dias(cfg):
            return True
    except CadenciaInvalida:
        return False
    return bool(cfg.get("interval_value") and cfg.get("interval_unit"))


# ── Calcular ─────────────────────────────────────────────────────────────


def proxima_corrida(
    agora: datetime,
    frequency: Optional[str],
    cfg: Optional[Dict[str, Any]] = None,
) -> Optional[datetime]:
    """Quando é a próxima corrida, em UTC. `None` = não corre sozinho.

    * dias da semana → o próximo desses dias, à hora escolhida (09:00 sem hora);
    * intervalo de dias/semanas com hora → alinhado a essa hora;
    * intervalo simples → agora + intervalo.

    Sempre ESTRITAMENTE no futuro: devolver «agora» punha o agente num ciclo
    apertado com o Beat.
    """
    if agora.tzinfo is None:
        agora = agora.replace(tzinfo=timezone.utc)
    cfg = cfg if isinstance(cfg, dict) else {}
    if str(frequency or "").lower() in SEM_CADENCIA and not _tem_cadencia_propria(cfg):
        return None

    fuso = _fuso(cfg)
    hora, minuto = hora_escolhida(cfg)
    try:
        dias = _dias(cfg)
    except CadenciaInvalida:
        dias = []

    if dias:
        h = HORA_POR_OMISSAO if hora is None else hora
        local = agora.astimezone(fuso)
        for d in range(0, 8):
            dia = (local + timedelta(days=d)).date()
            if dia.weekday() not in dias:
                continue
            candidato = datetime(dia.year, dia.month, dia.day, h, minuto, tzinfo=fuso)
            if candidato > agora:
                return candidato.astimezone(timezone.utc)
        # Inalcançável com pelo menos um dia escolhido; por segurança:
        return agora + timedelta(days=7)

    minutos = intervalo_em_minutos(cfg, frequency) or 1440
    if hora is not None and minutos >= 1440:
        local = agora.astimezone(fuso)
        candidato = datetime(local.year, local.month, local.day, hora, minuto, tzinfo=fuso)
        passo = timedelta(minutes=minutos)
        # `<=` e não `<`: correr agora e voltar a agendar para este mesmo
        # instante punha o agente num ciclo apertado.
        while candidato <= agora:
            candidato += passo
        return candidato.astimezone(timezone.utc)
    return agora + timedelta(minutes=minutos)


def proxima_corrida_do_agente(agente: Any, agora: Optional[datetime] = None) -> Optional[datetime]:
    return proxima_corrida(
        agora or datetime.now(timezone.utc),
        getattr(agente, "frequency", None),
        getattr(agente, "schedule_jsonb", None),
    )


def alinhado_a_hora(cfg: Any) -> bool:
    """Tem hora marcada (ou dias da semana)? Então não se estica por recuo."""
    if not isinstance(cfg, dict):
        return False
    try:
        if _dias(cfg):
            return True
    except CadenciaInvalida:
        return False
    return hora_escolhida(cfg)[0] is not None
