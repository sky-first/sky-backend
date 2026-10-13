"""Fontes do sistema — dados públicos que a Sky liga a um cliente com um checkbox.

Ver ``docs/contrato-fontes-do-sistema.md`` (contrato da API) e o desenho
aprovado pelo Lucas a 13/10/2026.

Módulos:

- ``catalogo``      — regras do catálogo (licença, plano, nomes de papéis).
- ``credenciais``   — onde vive a password do papel ``wt_<slug>``.
- ``mundo``         — GRANT/REVOKE na base ``sky_world`` com o ``world_admin``.
- ``ligacao_gerida`` — a ligação «Dados públicos» na base do cliente.
- ``provisionamento`` — converge um cliente para o estado pedido na Consola.
"""
