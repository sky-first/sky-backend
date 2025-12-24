#!/bin/bash
# Script para configurar Branch Protection Rules no GitHub
# Requer: GitHub CLI (gh) instalado e autenticado

set -e

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
echo "📦 Configurando Branch Protection para: $REPO"
echo ""

# Função para configurar proteção de branch
setup_protection() {
    local BRANCH=$1
    local REQUIRED_APPROVALS=${2:-1}
    
    echo "🔒 Configurando proteção para branch: $BRANCH"
    
    gh api repos/$REPO/branches/$BRANCH/protection \
        --method PUT \
        --field required_status_checks='{"strict":true,"contexts":["test"]}' \
        --field enforce_admins=true \
        --field required_pull_request_reviews='{"required_approving_review_count":'$REQUIRED_APPROVALS',"dismiss_stale_reviews":true,"require_code_owner_reviews":false}' \
        --field restrictions=null \
        --field allow_force_pushes=false \
        --field allow_deletions=false \
        --field required_linear_history=false \
        --field allow_squash_merge=true \
        --field allow_merge_commit=true \
        --field allow_rebase_merge=true \
        --field block_creations=false \
        --field required_conversation_resolution=false
    
    echo "✅ Branch '$BRANCH' protegida com sucesso!"
    echo ""
}

# Pergunta sobre número de approvals
echo "Quantos approvals são necessários? (padrão: 1)"
read -p "Digite o número (ou Enter para usar 1): " APPROVALS
APPROVALS=${APPROVALS:-1}

if [ "$APPROVALS" -lt 0 ] || [ "$APPROVALS" -gt 10 ]; then
    echo "❌ Número inválido. Usando padrão: 1"
    APPROVALS=1
fi

echo ""
echo "Configurando com $APPROVALS approval(s) necessário(s)..."
echo ""

# Configura staging
if gh api repos/$REPO/branches/staging --silent 2>/dev/null; then
    setup_protection "staging" $APPROVALS
else
    echo "⚠️  Branch 'staging' não encontrada. Pulando..."
    echo ""
fi

# Configura main
if gh api repos/$REPO/branches/main --silent 2>/dev/null; then
    setup_protection "main" $APPROVALS
else
    echo "⚠️  Branch 'main' não encontrada. Pulando..."
    echo ""
fi

echo "✨ Configuração concluída!"
echo ""
echo "📋 Resumo das proteções:"
echo "   - PR obrigatório antes de merge"
echo "   - $APPROVALS approval(s) necessário(s)"
echo "   - Status check 'test' obrigatório"
echo "   - Force push bloqueado"
echo "   - Deleção de branch bloqueada"
echo ""
echo "💡 Para verificar: Settings → Branches no GitHub"

