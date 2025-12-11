"use client"

import { useState, useEffect, useRef } from "react"
import { Rnd } from "react-rnd"
import { motion } from "framer-motion"
import { Sparkles } from "lucide-react"
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

// Helper function to validate widget position
const validatePosition = (pos: { x: number; y: number }) => {
    const x = typeof pos?.x === 'number' && !isNaN(pos.x) && isFinite(pos.x) ? pos.x : 0
    const y = typeof pos?.y === 'number' && !isNaN(pos.y) && isFinite(pos.y) ? pos.y : 0
    return { x, y }
}

export function WidgetContainer({ widget }: WidgetContainerProps) {
    const { updateWidget, removeWidget, selectWidget, selectedWidgetId, selectedWidgetIds, widgets } = useWidgetStore()
    const { scale, snapPosition } = useCanvasStore()
    const { openForWidget } = usePipelineStore()
    const { openForWidget: openAIChatbox } = useAIChatboxStore()
    const { isLocked } = useCanvasLockStore()
    const { activeTool } = useToolbarStore()
    const [isDragging, setIsDragging] = useState(false)
    const [isResizing, setIsResizing] = useState(false)
    
    // Validate and sanitize widget position
    const validWidgetPosition = validatePosition(widget.position || { x: 0, y: 0 })
    const [localPosition, setLocalPosition] = useState(validWidgetPosition)
    const [isNewWidget, setIsNewWidget] = useState(true)
    const isSelected = selectedWidgetId === widget.id || selectedWidgetIds.includes(widget.id)
    const isPlaceholder = widget.data?.isPlaceholder === true
    
    // Log position validation
    useEffect(() => {
        if (widget.position && (widget.position.x !== validWidgetPosition.x || widget.position.y !== validWidgetPosition.y)) {
            console.warn(`[WidgetContainer] ⚠️ Widget ${widget.id} had invalid position, corrected:`, {
                original: widget.position,
                corrected: validWidgetPosition
            })
        }
    }, [widget.id, widget.position?.x, widget.position?.y, validWidgetPosition.x, validWidgetPosition.y])
    
    // Mark widget as not new after initial mount (fade in animation duration)
    useEffect(() => {
        const timer = setTimeout(() => setIsNewWidget(false), 400) // Match fade in duration
        return () => clearTimeout(timer)
    }, [])
    
    // Log widget mount and validate DOM presence with retry mechanism
    useEffect(() => {
        console.log(`[WidgetContainer] 🎯 Widget ${widget.id} mounted at (${widget.position.x}, ${widget.position.y}), size: ${widget.size.width}x${widget.size.height}`)
        
        let retryCount = 0
        const maxRetries = 5
        
        const validateWidget = () => {
            const element = document.querySelector(`[data-widget-id="${widget.id}"]`) || 
                           document.querySelector(`[data-rnd="${widget.id}"]`)
            
            if (!element) {
                retryCount++
                if (retryCount < maxRetries) {
                    console.warn(`[WidgetContainer] ⚠️ Widget ${widget.id} not found, retry ${retryCount}/${maxRetries}...`)
                    setTimeout(validateWidget, 200 * retryCount) // Exponential backoff
                } else {
                    console.error(`[WidgetContainer] ❌ Widget ${widget.id} NOT FOUND IN DOM after ${maxRetries} retries!`)
                    console.error(`[WidgetContainer] Widget data:`, { id: widget.id, position: widget.position, size: widget.size })
                    console.error(`[WidgetContainer] All widgets in store:`, widgets.map(w => w.id))
                }
            } else {
                const rect = element.getBoundingClientRect()
                const isVisible = rect.width > 0 && rect.height > 0 && 
                                 rect.x !== 0 && rect.y !== 0 &&
                                 !element.hasAttribute('hidden') &&
                                 window.getComputedStyle(element).display !== 'none' &&
                                 window.getComputedStyle(element).visibility !== 'hidden'
                
                console.log(`[WidgetContainer] ✅ Widget ${widget.id} found in DOM:`, {
                    x: rect.x,
                    y: rect.y,
                    width: rect.width,
                    height: rect.height,
                    visible: isVisible,
                    zIndex: window.getComputedStyle(element).zIndex,
                    display: window.getComputedStyle(element).display,
                    opacity: window.getComputedStyle(element).opacity
                })
                
                if (!isVisible) {
                    console.warn(`[WidgetContainer] ⚠️ Widget ${widget.id} is in DOM but not visible!`)
                }
            }
        }
        
        // Initial validation after a short delay
        const validateTimer = setTimeout(validateWidget, 100)
        
        return () => clearTimeout(validateTimer)
    }, [widget.id, widget.position.x, widget.position.y, widget.size.width, widget.size.height, widgets])
    
    // Handler to open AI chatbox for placeholder widgets
    const handleOpenAI = (e?: React.MouseEvent) => {
        if (e) {
            e.stopPropagation()
        }
        openAIChatbox(widget.id, "", "")
    }
    
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
            const validated = validatePosition(widget.position || { x: 0, y: 0 })
            setLocalPosition(validated)
            console.log(`[WidgetContainer] 📍 Widget ${widget.id} position synced:`, validated)
        }
    }, [widget.position?.x, widget.position?.y, isDragging, widget.id])

    // Calculate z-index based on widget creation order (newer widgets on top)
    // Use widget index in the array to determine z-index
    const widgetIndex = widgets.findIndex(w => w.id === widget.id)
    const zIndex = widgetIndex >= 0 ? 10 + widgetIndex : 10
    
    // Log widget rendering with position info
    useEffect(() => {
        console.log(`[WidgetContainer] 🎨 Rendering widget ${widget.id}:`, {
            index: widgetIndex,
            zIndex: zIndex,
            position: validWidgetPosition,
            size: widget.size,
            localPosition: localPosition
        })
    }, [widget.id, widgetIndex, zIndex, validWidgetPosition.x, validWidgetPosition.y, widget.size.width, widget.size.height, localPosition.x, localPosition.y])
    
    return (
        <motion.div
            initial={isNewWidget ? { opacity: 0 } : false}
            animate={isNewWidget ? { opacity: 1 } : {}}
            transition={isNewWidget ? {
                duration: 0.4, // Professional fade in duration
                ease: [0.4, 0, 0.2, 1], // Smooth ease-in-out curve
                type: "tween"
            } : {}}
            style={{ 
                width: '100%', 
                height: '100%',
                position: 'relative' // Removed z-index from here - will be on Rnd
            }}
        >
        <Rnd
            data-widget-id={widget.id}
            data-rnd={widget.id}
            size={{ 
                width: typeof widget.size.width === 'number' && !isNaN(widget.size.width) ? widget.size.width : 250,
                height: typeof widget.size.height === 'number' && !isNaN(widget.size.height) ? widget.size.height : 150
            }}
            position={localPosition}
            disableDragging={isLocked}
            cancel=".widget-action-button, button, input, textarea, select"
            dragHandleClassName={undefined}
            style={{
                zIndex: zIndex,
                position: 'absolute' // Ensure Rnd uses absolute positioning
            }}
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
                const validated = validatePosition(snapped)
                setLocalPosition(validated)
                console.log(`[WidgetContainer] 🎯 Widget ${widget.id} drag stopped, position:`, validated)
                updateWidget(widget.id, { position: validated }, true) // Sync to backend
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
                const validatedPos = validatePosition({ x: position.x, y: position.y })
                const width = parseInt(ref.style.width) || widget.size.width
                const height = parseInt(ref.style.height) || widget.size.height
                setLocalPosition(validatedPos)
                console.log(`[WidgetContainer] 📏 Widget ${widget.id} resize stopped:`, { size: { width, height }, position: validatedPos })
                updateWidget(widget.id, {
                    size: { width, height },
                    position: validatedPos
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
                // Remove z-index classes - using inline style instead
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
                    isPlaceholder && "opacity-60 grayscale",
                    "py-0 gap-0 relative"
                )}>
                    {!isPlaceholder && (
                        <CardHeader className="px-2 pt-0.5 pb-1 flex flex-row items-center justify-center gap-0 relative">
                            <CardTitle className="text-sm font-semibold truncate leading-tight text-center text-foreground">
                                {widget.title}
                            </CardTitle>
                        </CardHeader>
                    )}
                    <CardContent 
                        className={cn(
                            "flex-1 p-4 overflow-auto widget-content relative",
                            isPlaceholder && "cursor-pointer"
                        )}
                        onDoubleClick={(e) => {
                            e.stopPropagation()
                            if (isPlaceholder) {
                                handleOpenAI(e)
                            } else {
                                const question = widget.data?.question ?? widget.title ?? ""
                                const answer = widget.data?.answer ?? 
                                    (widget.type === 'kpi' ? widget.data?.value ?? "" :
                                     widget.type === 'chart' ? "Chart visualization" :
                                     widget.type === 'table' ? "Table data" : "")
                                openAIChatbox(widget.id, question, answer)
                            }
                        }}
                        onClick={(e) => {
                            if (isPlaceholder && e.detail === 1) {
                                // Single click on placeholder - could open AI, but let's keep double click for now
                                // to avoid conflicts with selection
                            }
                        }}
                    >
                        {widget.type === 'kpi' && (
                            <div className="h-full flex items-center justify-center text-center relative">
                                {isPlaceholder ? (
                                    <div className="flex flex-col items-center justify-center gap-3 px-4 py-6">
                                        <Sparkles className="w-8 h-8 text-muted-foreground/40" />
                                        <p className="text-sm text-muted-foreground/70 leading-relaxed max-w-[200px] text-center">
                                            This widget comes to life with your data — ask AI to configure. <span className="font-medium">Double click.</span>
                                        </p>
                                    </div>
                                ) : (
                                    <div>
                                        <div className="text-3xl font-bold text-foreground">{widget.data.value}</div>
                                        <div className="text-green-500 text-xs font-medium">{widget.data.change}</div>
                                    </div>
                                )}
                            </div>
                        )}
                            {widget.type === 'chart' && (
                                <div className="w-full h-full min-w-0 min-h-0 flex-shrink-0 relative">
                                    {isPlaceholder ? (
                                        <div className="w-full h-full flex items-center justify-center px-4 py-6">
                                            <div className="flex flex-col items-center justify-center gap-3">
                                                <Sparkles className="w-8 h-8 text-muted-foreground/40" />
                                                <p className="text-sm text-muted-foreground/70 leading-relaxed max-w-[240px] text-center">
                                                    This widget comes to life with your data — ask AI to configure. <span className="font-medium">Double click.</span>
                                                </p>
                                            </div>
                                        </div>
                                    ) : (
                                        <ChartWidget 
                                            chartType={widget.data?.type || 'bar'}
                                            data={widget.data?.data}
                                            labels={widget.data?.labels}
                                            series={widget.data?.series}
                                        />
                                    )}
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
