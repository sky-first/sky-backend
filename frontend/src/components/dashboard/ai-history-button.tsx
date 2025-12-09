"use client"

import { Button } from "@/components/ui/button"
import { BookOpen } from "lucide-react"
import { useAIHistoryStore } from "@/store/ai-history-store"
import { useTheme } from "next-themes"
import { cn } from "@/lib/utils"
import { useEffect, useState } from "react"

export function AIHistoryButton() {
    const { isOpen, toggle } = useAIHistoryStore()
    const { theme, resolvedTheme } = useTheme()
    const [mounted, setMounted] = useState(false)

    useEffect(() => {
        setMounted(true)
    }, [])

    const currentTheme = resolvedTheme || theme || 'light'
    const isDark = currentTheme === 'dark'

    if (!mounted) return null

    const buttonStyle = {
        borderRadius: "0.75rem",
        padding: "0.75rem",
        border: isDark 
            ? "1px solid rgba(255, 255, 255, 0.08)" 
            : "1px solid rgba(0, 0, 0, 0.08)",
        background: isDark 
            ? "rgba(15, 23, 42, 0.35)" 
            : "rgba(255, 255, 255, 0.55)",
        backdropFilter: "blur(32px) saturate(180%)",
        WebkitBackdropFilter: "blur(32px) saturate(180%)",
        boxShadow: isDark 
            ? "0 4px 20px rgba(0, 0, 0, 0.25), 0 1px 4px rgba(0, 0, 0, 0.15), inset 0 1px 0 rgba(255, 255, 255, 0.05)" 
            : "0 4px 20px rgba(0, 0, 0, 0.08), 0 1px 4px rgba(0, 0, 0, 0.04), inset 0 1px 0 rgba(255, 255, 255, 0.8)",
    }

    return (
        <button
            data-tour="ai-history"
            className="fixed bottom-6 right-6 z-50 transition-all duration-200 pointer-events-auto group"
            style={buttonStyle}
            onClick={toggle}
            aria-label={isOpen ? "Close AI History" : "Open AI History"}
        >
            <div className={cn(
                "p-2 rounded-lg transition-all duration-200",
                isDark 
                    ? "hover:bg-white/8 active:bg-white/12" 
                    : "hover:bg-black/5 active:bg-black/10",
                isOpen && "bg-primary/20"
            )}>
                <BookOpen className={cn(
                    "w-5 h-5 transition-colors",
                    isDark ? "text-white/90" : "text-gray-900",
                    isOpen && "text-primary"
                )} />
            </div>
        </button>
    )
}

