"use client"

import { Button } from "@/components/ui/button"
import { Minus, Plus, RotateCcw, BookOpen } from "lucide-react"
import { useCanvasStore } from "@/store/canvas-store"
import { useAIHistoryStore } from "@/store/ai-history-store"
import { useTheme } from "next-themes"
import { cn } from "@/lib/utils"
import { useEffect, useState } from "react"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

export function CanvasControls() {
    const { zoomIn, zoomOut, resetView } = useCanvasStore()
    const { isOpen: isAIHistoryOpen, toggle: toggleAIHistory } = useAIHistoryStore()
    const { theme, resolvedTheme } = useTheme()
    const [mounted, setMounted] = useState(false)

    useEffect(() => {
        setMounted(true)
    }, [])

    const currentTheme = resolvedTheme || theme || 'light'
    const isDark = currentTheme === 'dark'

    if (!mounted) return null

    const containerStyle = {
        borderRadius: "0.75rem",
        padding: "0.5rem",
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

    const buttonHoverClass = cn(
        "rounded-lg transition-all duration-200",
        isDark 
            ? "hover:bg-white/8 active:bg-white/12" 
            : "hover:bg-black/5 active:bg-black/10"
    )

    return (
        <div 
            className="fixed bottom-6 right-6 z-50 flex flex-col gap-1.5 pointer-events-none"
            style={containerStyle}
        >
            <TooltipProvider delayDuration={0}>
                <div className="flex flex-col gap-1 pointer-events-auto">

                    {/* Zoom Controls */}
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button 
                                variant="ghost" 
                                size="icon"
                                className={cn("h-10 w-10", buttonHoverClass)}
                                onClick={zoomIn}
                                aria-label="Zoom in"
                            >
                                <Plus className={cn(
                                    "w-4 h-4 transition-colors",
                                    isDark ? "text-white/90" : "text-gray-900"
                                )} />
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent side="left" className="text-xs">
                            <div className="font-medium">Zoom In</div>
                        </TooltipContent>
                    </Tooltip>

                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button 
                                variant="ghost" 
                                size="icon"
                                className={cn("h-10 w-10", buttonHoverClass)}
                                onClick={resetView}
                                aria-label="Reset view"
                            >
                                <RotateCcw className={cn(
                                    "w-4 h-4 transition-colors",
                                    isDark ? "text-white/90" : "text-gray-900"
                                )} />
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent side="left" className="text-xs">
                            <div className="font-medium">Reset View</div>
                        </TooltipContent>
                    </Tooltip>

                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button 
                                variant="ghost" 
                                size="icon"
                                className={cn("h-10 w-10", buttonHoverClass)}
                                onClick={zoomOut}
                                aria-label="Zoom out"
                            >
                                <Minus className={cn(
                                    "w-4 h-4 transition-colors",
                                    isDark ? "text-white/90" : "text-gray-900"
                                )} />
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent side="left" className="text-xs">
                            <div className="font-medium">Zoom Out</div>
                        </TooltipContent>
                    </Tooltip>
                </div>
            </TooltipProvider>
        </div>
    )
}

