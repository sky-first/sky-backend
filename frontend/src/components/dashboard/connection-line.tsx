"use client"

import { Connection, Widget } from "@/store/widget-store"

interface ConnectionLineProps {
    connection: Connection
    fromWidget: Widget
    toWidget: Widget
    onDelete: (connectionId: string) => void
}

export function ConnectionLine({ connection, fromWidget, toWidget, onDelete }: ConnectionLineProps) {
    const getAnchorPoint = (widget: Widget, anchor: 'top' | 'right' | 'bottom' | 'left') => {
        const { x, y } = widget.position
        const { width, height } = widget.size
        
        switch (anchor) {
            case 'top':
                return { x: x + width / 2, y }
            case 'right':
                return { x: x + width, y: y + height / 2 }
            case 'bottom':
                return { x: x + width / 2, y: y + height }
            case 'left':
                return { x, y: y + height / 2 }
        }
    }
    
    const fromPoint = getAnchorPoint(fromWidget, connection.fromAnchor)
    const toPoint = getAnchorPoint(toWidget, connection.toAnchor)
    
    // Calculate control points for bezier curve
    const dx = toPoint.x - fromPoint.x
    const dy = toPoint.y - fromPoint.y
    const cp1x = fromPoint.x + dx * 0.5
    const cp1y = fromPoint.y
    const cp2x = toPoint.x - dx * 0.5
    const cp2y = toPoint.y
    
    const path = `M ${fromPoint.x} ${fromPoint.y} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${toPoint.x} ${toPoint.y}`
    
    return (
        <g>
            <path
                d={path}
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="text-primary"
                markerEnd="url(#arrowhead)"
            />
            <defs>
                <marker
                    id="arrowhead"
                    markerWidth="10"
                    markerHeight="10"
                    refX="9"
                    refY="3"
                    orient="auto"
                >
                    <polygon
                        points="0 0, 10 3, 0 6"
                        fill="currentColor"
                        className="text-primary"
                    />
                </marker>
            </defs>
        </g>
    )
}

