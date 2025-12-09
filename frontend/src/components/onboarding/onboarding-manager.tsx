"use client"

import { useState } from "react"
import { OnboardingTour, TourStep } from "./onboarding-tour"
import { OnboardingTriggerButton } from "./onboarding-trigger-button"

// Definir os steps do tour - Visão Geral Completa do Produto
const TOUR_STEPS: TourStep[] = [
    {
        id: 'welcome',
        target: '[data-tour="canvas"]',
        title: 'Bem-vindo ao Dashboard!',
        description: 'Este é um guia rápido para você conhecer todas as funcionalidades da plataforma. Vamos começar explorando os principais recursos disponíveis.',
        position: 'center',
        arrow: false,
        highlight: false,
    },
    {
        id: 'topbar',
        target: '[data-tour="topbar"]',
        title: 'Barra Superior',
        description: 'Aqui você gerencia seus workspaces, projetos e configurações. Use o menu Workspaces para alternar entre projetos pessoais e do time.',
        position: 'bottom',
        arrow: true,
        highlight: true,
    },
    {
        id: 'board-name',
        target: '[data-tour="board-name"]',
        title: 'Nome do Projeto',
        description: 'Clique aqui para editar o nome do seu dashboard. Organize seus projetos com nomes descritivos para facilitar a navegação.',
        position: 'bottom',
        arrow: true,
        highlight: true,
    },
    {
        id: 'user-menu',
        target: '[data-tour="user-menu-button"]',
        title: 'Menu do Usuário',
        description: 'Acesse suas configurações pessoais, preferências de tema (claro/escuro) e opções de conta. Clique no seu avatar para abrir o menu. Administradores também podem gerenciar conexões com bancos de dados e fontes de dados através da opção "Connections" neste menu.',
        position: 'bottom',
        arrow: true,
        highlight: true,
        action: () => {
            // Tentar abrir o menu do usuário se possível
            const userMenuButton = document.querySelector('[data-tour="user-menu-button"]') as HTMLElement
            if (userMenuButton) {
                userMenuButton.click()
            }
        }
    },
    {
        id: 'toolbar',
        target: '[data-tour="toolbar"]',
        title: 'Barra de Ferramentas',
        description: 'Aqui você encontra todas as ferramentas para criar seu dashboard: Text para textos, Templates para começar rápido, Shapes (retângulo, círculo, linha, seta), Charts (barra, pizza, linha, dispersão), Table para tabelas e Upload para arquivos CSV, Excel, imagens e PDFs.',
        position: 'right',
        arrow: true,
        highlight: true,
    },
    {
        id: 'ai-search',
        target: '[data-tour="ai-search"]',
        title: 'Assistente de IA',
        description: 'Faça perguntas em linguagem natural e nossa IA criará visualizações e análises automaticamente. Basta digitar sua pergunta e a IA fará o resto!',
        position: 'top',
        arrow: true,
        highlight: true,
    },
    {
        id: 'ai-history',
        target: '[data-tour="ai-history"]',
        title: 'Histórico de IA',
        description: 'Este botão no topo do grupo de controles (ícone de livro) abre o histórico completo de todas as suas interações com a IA. Revise perguntas anteriores, respostas geradas e análises criadas. Útil para referência e continuidade do trabalho.',
        position: 'top',
        arrow: true,
        highlight: true,
    },
    {
        id: 'widget-interaction',
        target: '[data-tour="canvas"]',
        title: 'Interagindo com Widgets',
        description: 'Clique em qualquer widget para selecioná-lo. Arraste para mover, use as bordas para redimensionar.',
        position: 'center',
        arrow: false,
        highlight: false,
    },
    {
        id: 'canvas-navigation',
        target: '[data-tour="canvas"]',
        title: 'Navegação no Canvas',
        description: 'Use a roda do mouse para zoom in/out, ou segure Space + arraste para mover o canvas. Todos os widgets são arrastáveis e redimensionáveis livremente.',
        position: 'center',
        arrow: false,
        highlight: false,
    },
    {
        id: 'help-button',
        target: '[data-tour="help-button"]',
        title: 'Ajuda e Suporte',
        description: 'Precisa de ajuda? Clique aqui para acessar documentação, tutoriais e suporte. Estamos sempre prontos para ajudar você a aproveitar ao máximo a plataforma.',
        position: 'top',
        arrow: true,
        highlight: true,
    },
    {
        id: 'final',
        target: '[data-tour="canvas"]',
        title: 'Pronto para começar!',
        description: 'Agora você conhece os principais recursos da plataforma. Comece criando widgets, explore os templates ou faça uma pergunta para a IA. Divirta-se criando dashboards incríveis!',
        position: 'center',
        arrow: false,
        highlight: false,
    },
]

export function OnboardingManager() {
    const [isTourOpen, setIsTourOpen] = useState(false)

    const handleStartTour = () => {
        setIsTourOpen(true)
    }

    const handleComplete = () => {
        console.log('Tour completed!')
        setIsTourOpen(false)
    }

    const handleSkip = () => {
        console.log('Tour skipped!')
        setIsTourOpen(false)
    }

    const handleClose = () => {
        setIsTourOpen(false)
    }

    return (
        <>
            <OnboardingTriggerButton onStart={handleStartTour} />
            <OnboardingTour
                steps={TOUR_STEPS}
                onComplete={handleComplete}
                onSkip={handleSkip}
                onClose={handleClose}
                storageKey="dashboard-onboarding-completed"
                showSkip={true}
                showProgress={true}
                autoStart={false}
                isOpen={isTourOpen}
            />
        </>
    )
}

