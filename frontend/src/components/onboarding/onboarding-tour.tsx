"use client"

import { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { X, ChevronRight, ChevronLeft, SkipForward } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { useTheme } from "next-themes"

export interface TourStep {
    id: string
    target: string // CSS selector ou ref
    title: string
    description: string
    position?: 'top' | 'bottom' | 'left' | 'right' | 'center'
    arrow?: boolean
    highlight?: boolean
    action?: () => void // Ação a executar antes de mostrar o step
}

interface OnboardingTourProps {
    steps: TourStep[]
    onComplete?: () => void
    onSkip?: () => void
    storageKey?: string
    showSkip?: boolean
    showProgress?: boolean
    autoStart?: boolean
    isOpen?: boolean
    onClose?: () => void
}

export function OnboardingTour({
    steps,
    onComplete,
    onSkip,
    storageKey = 'onboarding-completed',
    showSkip = true,
    showProgress = true,
    autoStart = true,
    isOpen: externalIsOpen,
    onClose: externalOnClose
}: OnboardingTourProps) {
    const [currentStep, setCurrentStep] = useState(0)
    const [isVisible, setIsVisible] = useState(false)
    const [targetElement, setTargetElement] = useState<HTMLElement | null>(null)
    const [tooltipPosition, setTooltipPosition] = useState({ top: 0, left: 0 })
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === 'dark'
    const tooltipRef = useRef<HTMLDivElement>(null)

    // Controlar visibilidade externamente ou internamente
    const isOpen = externalIsOpen !== undefined ? externalIsOpen : isVisible

    useEffect(() => {
        // Se controlado externamente, não fazer auto-start
        if (externalIsOpen !== undefined) {
            if (externalIsOpen) {
                setIsVisible(true)
                setCurrentStep(0)
                // Aguardar um pouco para o DOM estar pronto
                setTimeout(() => {
                    showStep(0)
                }, 100)
            } else {
                setIsVisible(false)
            }
            return
        }

        // Auto-start apenas se autoStart for true
        if (!autoStart) {
            return
        }

        // Verificar se já completou o tour
        const completed = localStorage.getItem(storageKey)
        if (completed === 'true') {
            return
        }

        // Iniciar tour após um pequeno delay
        const timer = setTimeout(() => {
            setIsVisible(true)
            setCurrentStep(0)
            showStep(0)
        }, 1000)

        return () => clearTimeout(timer)
    }, [storageKey, autoStart, externalIsOpen])

    const showStep = (stepIndex: number) => {
        if (stepIndex >= steps.length) {
            completeTour()
            return
        }

        const step = steps[stepIndex]
        
        // Executar ação se houver
        if (step.action) {
            step.action()
        }

        // Aguardar um pouco para o DOM atualizar
        setTimeout(() => {
            const element = document.querySelector(step.target) as HTMLElement
            if (element) {
                setTargetElement(element)
                updateTooltipPosition(element, step.position || 'bottom')
            } else {
                // Se não encontrou, tentar novamente após mais tempo
                console.warn(`Element not found: ${step.target}`)
                setTimeout(() => {
                    const retryElement = document.querySelector(step.target) as HTMLElement
                    if (retryElement) {
                        setTargetElement(retryElement)
                        updateTooltipPosition(retryElement, step.position || 'bottom')
                    }
                }, 300)
            }
        }, 200)
    }

    const updateTooltipPosition = (element: HTMLElement, position: string) => {
        const rect = element.getBoundingClientRect()
        const tooltipRect = tooltipRef.current?.getBoundingClientRect()
        const tooltipWidth = tooltipRect?.width || 320
        const tooltipHeight = tooltipRect?.height || 200
        const spacing = 16

        let top = 0
        let left = 0

        switch (position) {
            case 'top':
                top = rect.top - tooltipHeight - spacing
                left = rect.left + rect.width / 2 - tooltipWidth / 2
                break
            case 'bottom':
                top = rect.bottom + spacing
                left = rect.left + rect.width / 2 - tooltipWidth / 2
                break
            case 'left':
                top = rect.top + rect.height / 2 - tooltipHeight / 2
                left = rect.left - tooltipWidth - spacing
                break
            case 'right':
                top = rect.top + rect.height / 2 - tooltipHeight / 2
                left = rect.right + spacing
                break
            case 'center':
                top = window.innerHeight / 2 - tooltipHeight / 2
                left = window.innerWidth / 2 - tooltipWidth / 2
                break
        }

        // Ajustar para não sair da tela
        top = Math.max(10, Math.min(top, window.innerHeight - tooltipHeight - 10))
        left = Math.max(10, Math.min(left, window.innerWidth - tooltipWidth - 10))

        setTooltipPosition({ top, left })
    }

    const nextStep = () => {
        if (currentStep < steps.length - 1) {
            setCurrentStep(currentStep + 1)
            showStep(currentStep + 1)
        } else {
            completeTour()
        }
    }

    const previousStep = () => {
        if (currentStep > 0) {
            setCurrentStep(currentStep - 1)
            showStep(currentStep - 1)
        }
    }

    const completeTour = () => {
        if (externalIsOpen === undefined) {
            localStorage.setItem(storageKey, 'true')
        }
        setIsVisible(false)
        externalOnClose?.()
        onComplete?.()
    }

    const skipTour = () => {
        if (externalIsOpen === undefined) {
            localStorage.setItem(storageKey, 'true')
        }
        setIsVisible(false)
        externalOnClose?.()
        onSkip?.()
    }

    if (!isVisible || currentStep >= steps.length) return null

    const step = steps[currentStep]
    const progress = ((currentStep + 1) / steps.length) * 100

    return (
        <>
            {/* Overlay com highlight */}
            <AnimatePresence>
                {targetElement && step.highlight !== false && (
                    <>
                        <motion.div
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            className="fixed inset-0 z-[90] pointer-events-none"
                            style={{
                                background: 'rgba(0, 0, 0, 0.4)',
                                backdropFilter: 'blur(2px)',
                            }}
                        />
                        <motion.div
                            initial={{ opacity: 0, scale: 0.95 }}
                            animate={{ opacity: 1, scale: 1 }}
                            exit={{ opacity: 0, scale: 0.95 }}
                            className="fixed z-[91] pointer-events-none"
                            style={{
                                top: targetElement.getBoundingClientRect().top - 4,
                                left: targetElement.getBoundingClientRect().left - 4,
                                width: targetElement.getBoundingClientRect().width + 8,
                                height: targetElement.getBoundingClientRect().height + 8,
                                border: '3px solid #3b82f6',
                                borderRadius: '8px',
                                boxShadow: '0 0 0 9999px rgba(0, 0, 0, 0.4)',
                            }}
                        />
                    </>
                )}
            </AnimatePresence>

            {/* Tooltip */}
            <motion.div
                ref={tooltipRef}
                initial={{ opacity: 0, scale: 0.95, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 10 }}
                className={cn(
                    "fixed z-[100] w-80 rounded-lg shadow-2xl border",
                    "bg-background",
                    isDark 
                        ? "border-white/10 bg-gray-900" 
                        : "border-gray-200 bg-white"
                )}
                style={{
                    top: `${tooltipPosition.top}px`,
                    left: `${tooltipPosition.left}px`,
                }}
            >
                {/* Header */}
                <div className="flex items-start justify-between p-4 pb-3 border-b border-border">
                    <div className="flex-1">
                        <h3 className="text-base font-semibold text-foreground mb-1">
                            {step.title}
                        </h3>
                        {showProgress && (
                            <div className="flex items-center gap-2 mt-2">
                                <div className="flex-1 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                                    <motion.div
                                        initial={{ width: 0 }}
                                        animate={{ width: `${progress}%` }}
                                        className="h-full bg-blue-500 rounded-full"
                                    />
                                </div>
                                <span className="text-xs text-muted-foreground">
                                    {currentStep + 1}/{steps.length}
                                </span>
                            </div>
                        )}
                    </div>
                    {showSkip && (
                        <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 -mt-1 -mr-1"
                            onClick={skipTour}
                        >
                            <X className="h-4 w-4" />
                        </Button>
                    )}
                </div>

                {/* Content */}
                <div className="p-4">
                    <p className="text-sm text-muted-foreground leading-relaxed">
                        {step.description}
                    </p>
                </div>

                {/* Footer */}
                <div className="flex items-center justify-between p-4 pt-3 border-t border-border">
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={skipTour}
                        className="text-muted-foreground"
                    >
                        <SkipForward className="h-4 w-4 mr-1.5" />
                        Skip
                    </Button>
                    <div className="flex items-center gap-2">
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={previousStep}
                            disabled={currentStep === 0}
                        >
                            <ChevronLeft className="h-4 w-4 mr-1" />
                            Previous
                        </Button>
                        <Button
                            size="sm"
                            onClick={nextStep}
                        >
                            {currentStep === steps.length - 1 ? 'Finish' : 'Next'}
                            {currentStep < steps.length - 1 && (
                                <ChevronRight className="h-4 w-4 ml-1" />
                            )}
                        </Button>
                    </div>
                </div>

                {/* Arrow pointing to target */}
                {step.arrow !== false && targetElement && (
                    <div
                        className="absolute w-0 h-0"
                        style={{
                            [step.position === 'top' ? 'bottom' : 'top']: '-8px',
                            [step.position === 'left' || step.position === 'right' 
                                ? (step.position === 'left' ? 'right' : 'left')
                                : 'left']: '50%',
                            transform: step.position === 'left' || step.position === 'right'
                                ? 'translateY(-50%)'
                                : 'translateX(-50%)',
                            borderLeft: step.position === 'right' ? '8px solid transparent' : undefined,
                            borderRight: step.position === 'left' ? '8px solid transparent' : undefined,
                            borderTop: step.position === 'bottom' ? '8px solid transparent' : undefined,
                            borderBottom: step.position === 'top' ? '8px solid transparent' : undefined,
                            [step.position === 'right' ? 'borderLeftColor' : 
                             step.position === 'left' ? 'borderRightColor' :
                             step.position === 'bottom' ? 'borderTopColor' : 'borderBottomColor']: 
                                isDark ? '#1f2937' : '#ffffff',
                        }}
                    />
                )}
            </motion.div>
        </>
    )
}

