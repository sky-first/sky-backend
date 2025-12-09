"use client"

import { useState, useRef, useEffect } from "react"
import { BarChart3, PieChart, TrendingUp, Activity } from "lucide-react"
import { cn } from "@/lib/utils"
import { useTheme } from "next-themes"
import { motion, AnimatePresence } from "framer-motion"

interface ToolbarChartsMenuProps {
    onSelect: (chart: 'bar' | 'pie' | 'line' | 'scatter') => void
    isOpen: boolean
    onClose: () => void
    triggerRef?: React.RefObject<HTMLElement | null>
}

const charts = [
    { id: 'bar' as const, icon: BarChart3, label: 'Bar' },
    { id: 'pie' as const, icon: PieChart, label: 'Pie' },
    { id: 'line' as const, icon: TrendingUp, label: 'Line' },
    { id: 'scatter' as const, icon: Activity, label: 'Scatter' },
]

export function ToolbarChartsMenu({ onSelect, isOpen, onClose, triggerRef }: ToolbarChartsMenuProps) {
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === 'dark'
    const menuRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (!isOpen) return

        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Node
            
            // Check if click is outside menu
            const isOutsideMenu = menuRef.current && !menuRef.current.contains(target)
            
            // Check if click is outside trigger button
            const isOutsideTrigger = triggerRef?.current && !triggerRef.current.contains(target)
            
            // Close if click is outside both menu and trigger
            if (isOutsideMenu && (triggerRef ? isOutsideTrigger : true)) {
                onClose()
            }
        }

        // Use a small delay to avoid closing immediately when opening
        const timeoutId = setTimeout(() => {
            document.addEventListener('mousedown', handleClickOutside, true)
        }, 10)

        return () => {
            clearTimeout(timeoutId)
            document.removeEventListener('mousedown', handleClickOutside, true)
        }
    }, [isOpen, onClose, triggerRef])

    if (!isOpen) return null

    return (
        <AnimatePresence>
            <motion.div
                ref={menuRef}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                transition={{ duration: 0.15 }}
                className={cn(
                    "absolute left-full ml-2 p-1.5 rounded-lg shadow-lg border",
                    "bg-background/95 backdrop-blur-md",
                    isDark 
                        ? "border-white/10 bg-gray-900/95" 
                        : "border-gray-200/80 bg-white/95"
                )}
                style={{
                    boxShadow: isDark
                        ? "0 8px 24px rgba(0, 0, 0, 0.4), 0 2px 8px rgba(0, 0, 0, 0.2)"
                        : "0 8px 24px rgba(0, 0, 0, 0.12), 0 2px 8px rgba(0, 0, 0, 0.08)",
                }}
            >
                <div className="flex flex-col gap-0.5">
                    {charts.map((chart) => {
                        const Icon = chart.icon
                        return (
                            <button
                                key={chart.id}
                                onClick={() => {
                                    onSelect(chart.id)
                                    onClose()
                                }}
                                className={cn(
                                    "flex items-center gap-2.5 px-3 py-2 rounded-md text-sm",
                                    "transition-all duration-150",
                                    "hover:bg-accent",
                                    isDark
                                        ? "text-white/90 hover:bg-white/8"
                                        : "text-gray-700 hover:bg-gray-100"
                                )}
                            >
                                <Icon className="w-4 h-4" />
                                <span className="font-medium">{chart.label}</span>
                            </button>
                        )
                    })}
                </div>
            </motion.div>
        </AnimatePresence>
    )
}

