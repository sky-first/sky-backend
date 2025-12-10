"use client"

import { useState, useEffect, useRef } from "react"
import { Rnd } from "react-rnd"
import { motion } from "framer-motion"
import { useWidgetStore, Widget } from "@/store/widget-store"
import { useCanvasStore } from "@/store/canvas-store"
import { usePipelineStore } from "@/store/pipeline-store"
import { useAIChatboxStore } from "@/store/ai-chatbox-store"
import { useCanvasLockStore } from "@/store/canvas-lock-store"
import { useToolbarStore } from "@/store/toolbar-store"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { ChartWidget } from "@/components/widgets/chart-widget"
import { TextWidget } from "@/components/dashboard/text-widget"

interface WidgetContainerProps {
    widget: Widget
}

export function WidgetContainer({ widget }: WidgetContainerProps) {
    const { updateWidget, removeWidget, selectWidget, selectedWidgetId, selectedWidgetIds } = useWidgetStore()
    const { scale, snapPosition } = useCanvasStore()
    const { openForWidget } = usePipelineStore()
    const { openForWidget: openAIChatbox } = useAIChatboxStore()
    const { isLocked } = useCanvasLockStore()
    const { activeTool } = useToolbarStore()
    const [isDragging, setIsDragging] = useState(false)
    const [isResizing, setIsResizing] = useState(false)
    const [localPosition, setLocalPosition] = useState({ x: widget.position.x, y: widget.position.y })
    const [isNewWidget, setIsNewWidget] = useState(true)
    const isSelected = selectedWidgetId === widget.id || selectedWidgetIds.includes(widget.id)
    
    // Mark widget as not new after initial mount
    useEffect(() => {
        const timer = setTimeout(() => setIsNewWidget(false), 600)
        return () => clearTimeout(timer)
    }, [])
    
    // Handle keyboard delete
    useEffect(() => {
        if (!isSelected) return
        
        const handleKeyDown = (e: KeyboardEvent) => {
            if ((e.key === 'Backspace' || e.key === 'Delete') && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
                e.preventDefault()
                removeWidget(widget.id)
            }
        }
        
        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    }, [isSelected, widget.id, removeWidget])

    // Sync local position with widget position when not dragging
    useEffect(() => {
        if (!isDragging) {
            setLocalPosition({ x: widget.position.x, y: widget.position.y })
        }
    }, [widget.position.x, widget.position.y, isDragging])

    return (
        <motion.div
            initial={isNewWidget ? { scale: 0, opacity: 0 } : false}
            animate={isNewWidget ? { scale: 1, opacity: 1 } : {}}
            transition={isNewWidget ? {
                duration: 0.4,
                ease: "easeOut",
                type: "spring",
                stiffness: 200,
                damping: 20
            } : {}}
            style={{ width: '100%', height: '100%' }}
        >
        <Rnd
            size={{ width: widget.size.width, height: widget.size.height }}
            position={localPosition}
            disableDragging={isLocked}
            cancel=".widget-action-button, button, input, textarea, select"
            dragHandleClassName={undefined}
            onMouseDown={(e) => {
                // In selection mode, allow overlay to handle it
                // Otherwise, stop propagation to prevent canvas pan
                if (activeTool !== 'mouse') {
                    e.stopPropagation()
                }
            }}
            dragGrid={[1, 1]}
            enableResizing={isLocked ? false : {
                top: true,
                right: true,
                bottom: true,
                left: true,
                topRight: true,
                bottomRight: true,
                bottomLeft: true,
                topLeft: true,
            }}
            onDragStart={(e) => {
                // Prevent drag if canvas is locked
                if (isLocked) {
                    return false
                }
                
                // Don't allow drag in selection mode
                if (activeTool === 'mouse') {
                    return false
                }
                
                // For text widgets, only prevent drag if clicking directly on textarea or buttons
                if (widget.type === 'text') {
                    const target = e.target as HTMLElement
                    const isTextarea = target.tagName === 'TEXTAREA' || target.closest('textarea')
                    const isButton = target.closest('button')
                    
                    // Only prevent if clicking directly on textarea or buttons
                    if (isTextarea || isButton) {
                        return false
                    }
                    // If editing, don't allow drag
                    if (target.closest('[data-text-widget]')?.querySelector('textarea')) {
                        return false
                    }
                }
                
                setIsDragging(true)
                setLocalPosition({ x: widget.position.x, y: widget.position.y })
                selectWidget(widget.id)
            }}
            onDrag={(e, d) => {
                // Update local position only during drag for maximum fluidity
                // Don't update store until drag stops - this prevents store updates on every frame
                setLocalPosition({ x: d.x, y: d.y })
            }}
            onDragStop={(e, d) => {
                setIsDragging(false)
                // Apply snap and update store only when drag ends
                const snapped = snapPosition(d.x, d.y)
                setLocalPosition(snapped)
                updateWidget(widget.id, { position: snapped }, true) // Sync to backend
            }}
            onResizeStart={() => {
                setIsResizing(true)
                selectWidget(widget.id)
            }}
            onResize={(e, direction, ref, delta, position) => {
                // Update size in real-time for smooth resizing (no backend sync during resize)
                updateWidget(widget.id, {
                    size: { width: parseInt(ref.style.width), height: parseInt(ref.style.height) },
                    position: { x: position.x, y: position.y }
                }, false) // Don't sync to backend during resize
            }}
            onResizeStop={(e, direction, ref, delta, position) => {
                setIsResizing(false)
                updateWidget(widget.id, {
                    size: { width: parseInt(ref.style.width), height: parseInt(ref.style.height) },
                    position: { x: position.x, y: position.y }
                }, true) // Sync to backend when resize stops
            }}
            scale={scale}
            // Allow free movement - no bounds restriction
            // Allow dragging from anywhere in the card
            minWidth={widget.type === 'text' ? 100 : 200}
            minHeight={widget.type === 'text' ? 50 : 150}
            className={cn(
                // Disable transitions during drag for maximum performance
                !isDragging && !isResizing && "transition-all duration-150",
                isSelected ? "z-50" : "z-10",
                isDragging && "shadow-2xl",
                isResizing && "shadow-xl"
            )}
            style={{
                cursor: isDragging ? 'grabbing' : 'grab',
                // Optimize for drag performance
                willChange: isDragging ? 'transform' : 'auto',
                // Improve drag smoothness
                transform: 'translateZ(0)',
                backfaceVisibility: 'hidden',
            }}
            onClick={(e: React.MouseEvent) => {
                // Don't interfere with drag operations
                if (isDragging) {
                    return
                }
                
                // For text widgets, let the text widget handle clicks on the text content
                if (widget.type === 'text') {
                    const target = e.target as HTMLElement
                    const isTextarea = target.tagName === 'TEXTAREA' || target.closest('textarea')
                    const isButton = target.closest('button')
                    const isTextContent = target.closest('.text-widget-editable')
                    
                    // Let the text widget handle clicks on text content
                    if (isTextarea || isTextContent) {
                        return
                    }
                    // For buttons, stop propagation
                    if (isButton) {
                        e.stopPropagation()
                        return
                    }
                    // For container clicks (empty space), just select
                    selectWidget(widget.id)
                    return
                }
                
                e.stopPropagation()
                selectWidget(widget.id)
            }}
            onDoubleClick={(e: React.MouseEvent) => {
                // Don't interfere with drag operations
                if (isDragging) {
                    return
                }
                
                e.stopPropagation()
                
                // Open AI chatbox on double click with widget information
                const question = widget.data?.question ?? widget.title ?? ""
                const answer = widget.data?.answer ?? 
                    (widget.type === 'kpi' ? widget.data?.value ?? "" :
                     widget.type === 'chart' ? "Chart visualization" :
                     widget.type === 'table' ? "Table data" : "")
                
                openAIChatbox(widget.id, question, answer)
            }}
        >
                {widget.type === 'text' ? (
                    // Text widgets have a simpler layout without Card wrapper
                    <div 
                        data-text-widget
                        data-widget-id={widget.id}
                        className={cn(
                            "w-full h-full relative",
                            "transition-all duration-300 ease-out",
                            isSelected && "ring-2 ring-blue-500/60",
                            !widget.data?.backgroundColor || widget.data.backgroundColor === 'transparent' 
                                ? "bg-transparent" 
                                : ""
                        )}
                        style={{
                            backgroundColor: widget.data?.backgroundColor && widget.data.backgroundColor !== 'transparent' 
                                ? widget.data.backgroundColor 
                                : 'transparent',
                            WebkitFontSmoothing: 'antialiased',
                            MozOsxFontSmoothing: 'grayscale',
                            textRendering: 'optimizeLegibility',
                            backfaceVisibility: 'hidden',
                            transform: 'translateZ(0)',
                        }}
                        onMouseDown={(e) => {
                            // Only prevent canvas pan for textarea and buttons
                            // Let everything else bubble so Rnd can handle drag
                            const target = e.target as HTMLElement
                            const isTextarea = target.tagName === 'TEXTAREA' || target.closest('textarea')
                            const isButton = target.closest('button')
                            
                            if (isTextarea || isButton) {
                                e.stopPropagation()
                            }
                            // Don't stop propagation for container - this allows Rnd to detect drag
                        }}
                    >
                    <TextWidget
                        widget={widget}
                        isSelected={isSelected}
                        onUpdate={(content) => updateWidget(widget.id, { data: { ...widget.data, content } })}
                        onSelect={() => selectWidget(widget.id)}
                        onResize={(height, width) => {
                            // Update widget size to match textarea content
                            const minHeight = 50
                            const minWidth = 100
                            const newHeight = Math.max(minHeight, Math.ceil(height))
                            const newWidth = width ? Math.max(minWidth, Math.ceil(width)) : widget.size.width
                            
                            // Always update to ensure sync, even if values are close
                            const heightDiff = Math.abs(newHeight - widget.size.height)
                            const widthDiff = Math.abs(newWidth - widget.size.width)
                            
                            if (heightDiff > 1 || widthDiff > 1) {
                                updateWidget(widget.id, {
                                    size: { width: newWidth, height: newHeight }
                                })
                            }
                        }}
                    />
                </div>
            ) : (
                <Card className={cn(
                    "w-full h-full flex flex-col overflow-hidden shadow-sm hover:shadow-md group cursor-grab active:cursor-grabbing",
                    // Disable transitions during drag for better performance
                    !isDragging && "transition-all",
                    isSelected ? "ring-2 ring-blue-600 dark:ring-blue-400 shadow-xl" : "",
                    isDragging && "ring-2 ring-primary/50",
                    "py-0 gap-0"
                )}>
                    <CardHeader className="px-2 pt-0.5 pb-1 flex flex-row items-center justify-center gap-0 relative">
                        <CardTitle className="text-sm font-semibold text-foreground truncate leading-tight text-center">
                            {widget.title}
                        </CardTitle>
                    </CardHeader>
                    <CardContent 
                        className="flex-1 p-4 overflow-auto widget-content"
                        onDoubleClick={(e) => {
                            e.stopPropagation()
                            const question = widget.data?.question ?? widget.title ?? ""
                            const answer = widget.data?.answer ?? 
                                (widget.type === 'kpi' ? widget.data?.value ?? "" :
                                 widget.type === 'chart' ? "Chart visualization" :
                                 widget.type === 'table' ? "Table data" : "")
                            openAIChatbox(widget.id, question, answer)
                        }}
                    >
                        {widget.type === 'kpi' && (
                            <div className="h-full flex items-center justify-center text-center">
                                <div>
                                    <div className="text-3xl font-bold text-foreground">{widget.data.value}</div>
                                    <div className="text-green-500 text-xs font-medium">{widget.data.change}</div>
                                </div>
                            </div>
                        )}
                            {widget.type === 'chart' && (
                                <div className="w-full h-full min-w-0 min-h-0 flex-shrink-0">
                                    <ChartWidget 
                                        chartType={widget.data?.type || 'bar'}
                                        data={widget.data?.data}
                                        labels={widget.data?.labels}
                                        series={widget.data?.series}
                                    />
                                </div>
                            )}
                        {widget.type === 'table' && (
                            <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                                Table Placeholder
                            </div>
                        )}
                        {widget.type === 'ai-box' && (
                            <div className="w-full h-full flex flex-col p-4 gap-3">
                                {widget.data?.question && (
                                    <div className="mb-2">
                                        <p className="text-sm font-medium text-muted-foreground mb-1">Question:</p>
                                        <p className="text-sm italic text-foreground/80">{widget.data.question}</p>
                                    </div>
                                )}
                                {widget.data?.answer && (
                                    <div className="flex-1 overflow-auto">
                                        <p className="text-sm font-medium text-muted-foreground mb-2">Answer:</p>
                                        <div className="text-sm text-foreground whitespace-pre-line leading-relaxed">
                                            {widget.data.answer}
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    </CardContent>
                </Card>
            )}
        </Rnd>
        </motion.div>
    )
}
