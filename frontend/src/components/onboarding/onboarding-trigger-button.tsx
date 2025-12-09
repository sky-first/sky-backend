"use client"

import { useState } from "react"
import { HelpCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { useTheme } from "next-themes"
import { motion } from "framer-motion"

interface OnboardingTriggerButtonProps {
    onStart: () => void
}

export function OnboardingTriggerButton({ onStart }: OnboardingTriggerButtonProps) {
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === 'dark'

    return (
        <motion.div
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            className="fixed bottom-6 right-24 z-50"
        >
            <Button
                onClick={onStart}
                className={cn(
                    "h-12 w-12 rounded-full shadow-lg",
                    "bg-blue-500 hover:bg-blue-600",
                    "text-white",
                    "transition-all duration-200",
                    "hover:scale-110 active:scale-95"
                )}
                aria-label="Iniciar tour guiado"
            >
                <HelpCircle className="h-6 w-6" />
            </Button>
        </motion.div>
    )
}

