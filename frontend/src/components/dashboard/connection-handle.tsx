"use client"

import { ArrowUp, ArrowRight, ArrowDown, ArrowLeft } from "lucide-react"
import { cn } from "@/lib/utils"

interface ConnectionHandleProps {
    anchor: 'top' | 'right' | 'bottom' | 'left'
    onMouseDown: (e: React.MouseEvent, anchor: 'top' | 'right' | 'bottom' | 'left') => void
    isConnecting: boolean
}

export function ConnectionHandle({ anchor, onMouseDown, isConnecting }: ConnectionHandleProps) {
    const getIcon = () => {
        switch (anchor) {
            case 'top': return <ArrowUp className="w-3.5 h-3.5 text-white" strokeWidth={2.5} />
            case 'right': return <ArrowRight className="w-3.5 h-3.5 text-white" strokeWidth={2.5} />
            case 'bottom': return <ArrowDown className="w-3.5 h-3.5 text-white" strokeWidth={2.5} />
            case 'left': return <ArrowLeft className="w-3.5 h-3.5 text-white" strokeWidth={2.5} />
        }
    }

    const getPosition = () => {
        switch (anchor) {
            case 'top': return "top-0 left-1/2 -translate-x-1/2 -translate-y-1/2"
            case 'right': return "top-1/2 right-0 -translate-y-1/2 translate-x-1/2"
            case 'bottom': return "bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2"
            case 'left': return "top-1/2 left-0 -translate-y-1/2 -translate-x-1/2"
        }
    }

    return (
        <div
            onMouseDown={(e) => {
                e.preventDefault()
                e.stopPropagation()
                onMouseDown(e, anchor)
            }}
            onClick={(e) => {
                // Prevent click from bubbling to widget
                e.preventDefault()
                e.stopPropagation()
            }}
            className={cn(
                "absolute",
                getPosition(),
                "w-6 h-6 rounded-full bg-blue-600",
                "flex items-center justify-center",
                "cursor-crosshair shadow-md hover:shadow-lg hover:bg-blue-700",
                "z-[60] pointer-events-auto transition-all",
                isConnecting && "ring-2 ring-blue-400 ring-offset-2"
            )}
            aria-label={`Connect from ${anchor}`}
        >
            {getIcon()}
        </div>
    )
}

