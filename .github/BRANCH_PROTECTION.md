# 🔒 Guia: Configurar Branch Protection Rules

Este guia explica como configurar Branch Protection Rules para as branches `staging` e `main`.

## 🚀 Método 1: Script Automático (Recomendado)

### Pré-requisitos
- GitHub CLI (`gh`) instalado
- Autenticado no GitHub (`gh auth login`)

### Executar
```bash
cd /Users/thedatafirst/skyfirst/repositories/sky-poc-backend
chmod +x .github/scripts/setup-branch-protection.sh
.github/scripts/setup-branch-protection.sh
```

O script irá:
- Detectar o repositório automaticamente
- Configurar proteção para `staging` e `main`
- Perguntar quantos approvals são necessários (padrão: 1)

---

## 📝 Método 2: Configuração Manual

### Passo a passo

1. **Acesse o repositório no GitHub**
   - Vá para: `https://github.com/SEU_ORG/SEU_REPO`
   - Clique em **Settings** → **Branches**

2. **Configure proteção para `staging`**
   - Clique em **Add branch protection rule**
   - Em **Branch name pattern**, digite: `staging`
   - Marque as seguintes opções:
     - ✅ **Require a pull request before merging**
       - ✅ **Require approvals**: `1` (ou `0` se time muito pequeno)
       - ✅ **Dismiss stale pull request approvals when new commits are pushed**
     - ✅ **Require status checks to pass before merging**
       - ✅ **Require branches to be up to date before merging**
       - Na lista, marque: **test** (job do CI)
     - ✅ **Require conversation resolution before merging** (opcional)
     - ✅ **Do not allow bypassing the above settings**
   - Em **Restrict who can push to matching branches**: deixe vazio (ou adicione admins se quiser)
   - Clique em **Create**

3. **Configure proteção para `main`**
   - Repita o passo 2, mas use o padrão: `main`
   - Recomendação: use `1` approval mínimo para `main`

4. **Proteções adicionais (recomendado)**
   - ✅ **Block force pushes**
   - ✅ **Block deletion of this branch**

---

## ✅ Verificação

Após configurar, teste:

1. Crie uma branch `feature/test`
2. Faça um commit e abra um PR para `staging`
3. Verifique que:
   - O PR não pode ser mergeado sem aprovação
   - O PR não pode ser mergeado se o CI falhar
   - Force push está bloqueado

---

## 🔧 Configurações Aplicadas

### Para `staging` e `main`:
- ✅ PR obrigatório antes de merge
- ✅ 1 approval necessário (configurável)
- ✅ Status check `test` obrigatório
- ✅ Branch deve estar atualizada antes do merge
- ✅ Force push bloqueado
- ✅ Deleção de branch bloqueada

---

## 🆘 Troubleshooting

### "Status check 'test' não aparece na lista"
- **Causa**: O workflow ainda não rodou
- **Solução**: Abra um PR de teste e aguarde o CI rodar. Depois, o status check aparecerá na lista.

### "Não consigo fazer merge mesmo com aprovação"
- Verifique se o CI passou
- Verifique se a branch está atualizada com a base
- Verifique se não há conflitos

### "Quero mudar o número de approvals"
- Vá em Settings → Branches
- Clique na regra da branch
- Altere "Required number of approvals"
- Salve

---

## 📚 Referências

- [GitHub Docs: Branch Protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [GitHub CLI: gh api](https://cli.github.com/manual/gh_api)

