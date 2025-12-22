# Estratégia de testes (visão simples)

Queremos evitar que erros e quebras cheguem a produção. Para isso usamos três pilares: revisar infraestrutura antes de aplicar, testar e checar segurança do backend, e validar o deploy com checagens rápidas.

## Infraestrutura
- Sempre que abrimos PR ou damos push em `infra/azure`, rodamos formatação e validação do Terraform.
- No PR geramos um plano de mudanças para revisar antes de aplicar, evitando alterações destrutivas por engano.
- Também verificamos arquivos YAML dos workflows para não quebrar automações.

## Backend
- Para PRs e pushes em `staging`/`main`, rodamos checagens básicas de código (estilo/erros) e testes automatizados com cobertura mínima de 70%.
- Fazemos varreduras de segurança em código e dependências e uma revisão rápida das dependências adicionadas.
- Um comentário no PR resume o resultado das etapas.

## Deploy do backend
- Antes de publicar, rodamos um conjunto pequeno de “smoke tests” para garantir que o básico funciona.
- O deploy pode ser padrão ou blue/green, via script de VM.
- Depois do deploy executamos um health check; se falhar em produção, temos passo de rollback.

## Quando consideramos aprovado
- Infra: plano sem destruição acidental e validações passando.
- Backend: testes e checagens de código/segurança ok, cobertura ≥ 70%.
- Deploy: smoke + health checks passando.

## Dicas rápidas locais
- Infra: `cd infra/azure && terraform fmt -recursive && terraform validate`
- Backend: instalar dependências e rodar lint + testes: `black .`, `flake8`, `mypy`, `pytest --cov --cov-fail-under=70`, `bandit`, `safety`
