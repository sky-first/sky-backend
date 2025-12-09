"use client"

import { ConnectionHandle } from "./connection-handle"

interface ConnectionArrowsProps {
    widgetId: string
    onArrowMouseDown: (e: React.MouseEvent, anchor: 'top' | 'right' | 'bottom' | 'left') => void
    isConnecting: boolean
}

export function ConnectionArrows({ widgetId, onArrowMouseDown, isConnecting }: ConnectionArrowsProps) {
    return (
        <>
            <ConnectionHandle anchor="top" onMouseDown={onArrowMouseDown} isConnecting={isConnecting} />
            <ConnectionHandle anchor="right" onMouseDown={onArrowMouseDown} isConnecting={isConnecting} />
            <ConnectionHandle anchor="bottom" onMouseDown={onArrowMouseDown} isConnecting={isConnecting} />
            <ConnectionHandle anchor="left" onMouseDown={onArrowMouseDown} isConnecting={isConnecting} />
        </>
    )
}

