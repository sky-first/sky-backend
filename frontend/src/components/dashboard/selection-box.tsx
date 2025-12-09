"use client"

import { cn } from "@/lib/utils"

interface SelectionBoxProps {
    start: { x: number; y: number }
    end: { x: number; y: number }
    visible: boolean
}

export function SelectionBox({ start, end, visible }: SelectionBoxProps) {
    if (!visible) return null

    const left = Math.min(start.x, end.x)
    const top = Math.min(start.y, end.y)
    const width = Math.abs(end.x - start.x)
    const height = Math.abs(end.y - start.y)

    return (
        <div
            className="absolute border-2 border-blue-500 bg-blue-500/20 pointer-events-none z-50"
            style={{
                left: `${left}px`,
                top: `${top}px`,
                width: `${width}px`,
                height: `${height}px`,
            }}
        />
    )
}

