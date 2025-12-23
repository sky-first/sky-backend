"use client"

import { useState, useEffect, useRef, useCallback, useMemo, memo } from "react"
import { Rnd } from "react-rnd"
import { motion } from "framer-motion"
import { Sparkles, ScanSearch, MessageSquareText, Copy, Code2, Table2 } from "lucide-react"
import { useWidgetStore, Widget } from "@/store/widget-store"
import { useCanvasStore } from "@/store/canvas-store"
import { usePipelineStore } from "@/store/pipeline-store"
import { useAIChatboxStore } from "@/store/ai-chatbox-store"
import { useCanvasLockStore } from "@/store/canvas-lock-store"
import { useToolbarStore } from "@/store/toolbar-store"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
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

function WidgetContainerComponent({ widget }: WidgetContainerProps) {
    // Use Zustand selectors to avoid unnecessary re-renders
    const updateWidget = useWidgetStore(state => state.updateWidget)
    const removeWidget = useWidgetStore(state => state.removeWidget)
    const selectWidget = useWidgetStore(state => state.selectWidget)
    const selectedWidgetId = useWidgetStore(state => state.selectedWidgetId)
    const selectedWidgetIds = useWidgetStore(state => state.selectedWidgetIds)
    const widgets = useWidgetStore(state => state.widgets)
    const scale = useCanvasStore(state => state.scale)
    const snapPosition = useCanvasStore(state => state.snapPosition)
    const openForWidget = usePipelineStore(state => state.openForWidget)
    const openAIChatbox = useAIChatboxStore(state => state.openForWidget)
    const isLocked = useCanvasLockStore(state => state.isLocked)
    const activeTool = useToolbarStore(state => state.activeTool)
    const [isDragging, setIsDragging] = useState(false)
    const [isResizing, setIsResizing] = useState(false)
    const [isInspectOpen, setIsInspectOpen] = useState(false)
    
    // Validate and sanitize widget position - memoize
    const validWidgetPosition = useMemo(() => 
        validatePosition(widget.position || { x: 0, y: 0 }),
        [widget.position?.x, widget.position?.y]
    )
    const [localPosition, setLocalPosition] = useState(validWidgetPosition)
    const [isNewWidget, setIsNewWidget] = useState(true)
    
    // Memoize derived values
    const isSelected = useMemo(() => 
        selectedWidgetId === widget.id || selectedWidgetIds.includes(widget.id),
        [selectedWidgetId, widget.id, selectedWidgetIds]
    )
    const isPlaceholder = useMemo(() => 
        widget.data?.isPlaceholder === true,
        [widget.data?.isPlaceholder]
    )

    const widgetKindLabel = useMemo(() => {
        switch (widget.type) {
            case "kpi":
                return "KPI"
            case "chart":
                return "Chart"
            case "table":
                return "Table"
            case "text":
                return "Text"
            default:
                return "Widget"
        }
    }, [widget.type])

    const accent = useMemo(() => {
        // Accent per widget type (matches Tremor-like soft cards)
        if (widget.type === "kpi") return { bar: "bg-blue-500", bg: "" }
        if (widget.type === "chart") {
            const t = String(widget.data?.type || "bar")
            if (t === "pie") return { bar: "bg-blue-500", bg: "" }
            if (t === "scatter") return { bar: "bg-blue-500", bg: "" }
            if (t === "line" || t === "area") return { bar: "bg-blue-500", bg: "" }
            return { bar: "bg-blue-500", bg: "" }
        }
        if (widget.type === "table") return { bar: "bg-blue-500", bg: "" }
        if (widget.type === "text") return { bar: "bg-blue-500", bg: "" }
        return { bar: "bg-blue-500", bg: "" }
    }, [widget.type, widget.data?.type])

    const deltaBadge = useMemo(() => {
        const raw = widget.data?.change
        if (raw == null) return null
        const text = String(raw)
        const isNeg = text.includes("-")
        return {
            text,
            className: isNeg
                ? "bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20"
                : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20",
        }
    }, [widget.data?.change])

    const kpiValue = useMemo(() => {
        // Prefer existing value (used by some widget generators)
        const direct = widget.data?.value
        if (direct !== undefined && direct !== null && String(direct).trim() !== "") {
            return String(direct)
        }

        // AI-built KPI widgets currently store query output in { answer, data, sql }
        const data = widget.data?.data
        if (Array.isArray(data) && data.length > 0 && data[0] && typeof data[0] === "object") {
            const firstRow = data[0] as Record<string, any>
            const keys = Object.keys(firstRow)
            // pick first numeric-looking field
            for (const k of keys) {
                const v = firstRow[k]
                if (typeof v === "number" && isFinite(v)) return v.toLocaleString()
                if (typeof v === "string" && v.trim() && !isNaN(Number(v))) return Number(v).toLocaleString()
            }
            if (keys.length > 0 && firstRow[keys[0]] != null) return String(firstRow[keys[0]])
        }

        const answer = widget.data?.answer
        if (typeof answer === "string" && answer.trim()) return answer.trim()
        return "—"
    }, [widget.data?.value, widget.data?.data, widget.data?.answer])

    const tableModel = useMemo(() => {
        const data = widget.data?.data
        if (!Array.isArray(data) || data.length === 0) return { columns: [], rows: [] as any[] }
        const first = data.find((r) => r && typeof r === "object") as Record<string, any> | undefined
        if (!first) return { columns: [], rows: [] as any[] }
        const columns = Object.keys(first).slice(0, 8)
        const rows = data.slice(0, 15)
        return { columns, rows }
    }, [widget.data?.data])

    const handleCopyToClipboard = useCallback(async (text: string) => {
        try {
            if (!text) return
            await navigator.clipboard.writeText(text)
        } catch {
            // ignore
        }
    }, [])
    
    // Memoize widget index and z-index
    const widgetIndex = useMemo(() => 
        widgets.findIndex(w => w.id === widget.id),
        [widgets, widget.id]
    )
    const zIndex = useMemo(() => 
        widgetIndex >= 0 ? 100 + widgetIndex : 100,
        [widgetIndex]
    )
    
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
    
    // Handler to open AI chatbox for placeholder widgets - memoized
    const handleOpenAI = useCallback((e?: React.MouseEvent) => {
        if (e) {
            e.stopPropagation()
        }
        openAIChatbox(widget.id, "", "")
    }, [widget.id, openAIChatbox])
    
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

    // Widget index and z-index are already memoized above
    
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
            animate={isNewWidget ? { opacity: 1 } : { opacity: 1 }}
            transition={isNewWidget ? {
                duration: 0.4, // Professional fade in duration
                ease: [0.4, 0, 0.2, 1], // Smooth ease-in-out curve
                type: "tween"
            } : {}}
            onAnimationComplete={() => {
                setIsNewWidget(false)
            }}
            style={{ 
                // Prevent the wrapper from taking space and pushing other widgets
                position: 'absolute',
                top: 0,
                left: 0,
                width: 0,
                height: 0,
                overflow: 'visible'
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
                position: 'absolute', // Ensure Rnd uses absolute positioning
                opacity: 1,
                visibility: 'visible',
                display: 'block',
                cursor: isDragging ? 'grabbing' : 'grab',
                // Optimize for drag performance
                willChange: isDragging ? 'transform' : 'auto',
                // Improve drag smoothness
                transform: 'translateZ(0)',
                backfaceVisibility: 'hidden',
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
            onDragStart={useCallback((e: any) => {
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
            }, [isLocked, activeTool, widget.type, widget.position.x, widget.position.y, widget.id, selectWidget])}
            onDrag={useCallback((e: any, d: { x: number; y: number }) => {
                // Update local position only during drag for maximum fluidity
                // Don't update store until drag stops - this prevents store updates on every frame
                setLocalPosition({ x: d.x, y: d.y })
            }, [])}
            onDragStop={useCallback((e: any, d: { x: number; y: number }) => {
                setIsDragging(false)
                // Apply snap and update store only when drag ends
                const snapped = snapPosition(d.x, d.y)
                const validated = validatePosition(snapped)
                setLocalPosition(validated)
                console.log(`[WidgetContainer] 🎯 Widget ${widget.id} drag stopped, position:`, validated)
                updateWidget(widget.id, { position: validated }, true) // Sync to backend
            }, [widget.id, snapPosition, updateWidget])}
            onResizeStart={useCallback(() => {
                setIsResizing(true)
                selectWidget(widget.id)
            }, [widget.id, selectWidget])}
            onResize={useCallback((e: any, direction: any, ref: HTMLElement, delta: any, position: { x: number; y: number }) => {
                // Update size in real-time for smooth resizing (no backend sync during resize)
                updateWidget(widget.id, {
                    size: { width: parseInt(ref.style.width), height: parseInt(ref.style.height) },
                    position: { x: position.x, y: position.y }
                }, false) // Don't sync to backend during resize
            }, [widget.id, updateWidget])}
            onResizeStop={useCallback((e: any, direction: any, ref: HTMLElement, delta: any, position: { x: number; y: number }) => {
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
            }, [widget.id, widget.size.width, widget.size.height, updateWidget])}
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
            onClick={useCallback((e: React.MouseEvent) => {
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
            }, [isDragging, widget.type, widget.id, selectWidget])}
            onDoubleClick={useCallback((e: React.MouseEvent) => {
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
            }, [isDragging, widget.id, widget.data?.question, widget.data?.answer, widget.title, widget.type, widget.data?.value, openAIChatbox])}
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
                <>
                <Card className={cn(
                    // Card shell (clean + modern; works well on light/dark)
                    "w-full h-full flex flex-col overflow-hidden group cursor-grab active:cursor-grabbing",
                    "rounded-2xl",
                    // Tremor demo style: pure white surface + soft shadow
                    "bg-white",
                    "border border-slate-100 shadow-[0_6px_24px_rgba(15,23,42,0.06)]",
                    "hover:shadow-[0_10px_32px_rgba(15,23,42,0.10)] hover:border-slate-200",
                    // Disable transitions during drag for better performance
                    !isDragging && "transition-all",
                    isSelected ? "ring-2 ring-blue-600 dark:ring-blue-400 shadow-xl" : "",
                    isDragging && "ring-2 ring-primary/50",
                    isPlaceholder && "opacity-60 grayscale",
                    "py-0 gap-0 relative"
                )}>
                    <CardHeader className={cn(
                        "px-4 pt-3 pb-3 flex flex-row items-center justify-between gap-2 border-b border-slate-100",
                        isPlaceholder && "opacity-80"
                    )}>
                            <div className="min-w-0 flex-1">
                                <CardTitle className="text-sm font-semibold leading-tight text-primary break-words whitespace-normal line-clamp-2">
                                    {widget.title}
                                </CardTitle>
                            </div>
                            {!isPlaceholder ? (
                                <div className="flex items-center gap-2">
                                    {deltaBadge ? (
                                        <span className={cn("shrink-0 text-[10px] font-semibold border rounded-full px-2 py-0.5", deltaBadge.className)}>
                                            {deltaBadge.text}
                                        </span>
                                    ) : null}
                                    <TooltipProvider delayDuration={150}>
                                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        className="h-7 w-7 p-0"
                                                        onClick={(e) => {
                                                            e.stopPropagation()
                                                            setIsInspectOpen(true)
                                                        }}
                                                        aria-label="Overview"
                                                    >
                                                        <ScanSearch className="h-4 w-4" />
                                                    </Button>
                                                </TooltipTrigger>
                                                <TooltipContent side="bottom" className="text-xs">
                                                    Overview
                                                </TooltipContent>
                                            </Tooltip>

                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        className="h-7 w-7 p-0"
                                                        onClick={(e) => {
                                                            e.stopPropagation()
                                                            const question = String(widget.data?.question ?? widget.title ?? "")
                                                            const answer = String(widget.data?.answer ?? "")
                                                            openAIChatbox(widget.id, question, answer)
                                                        }}
                                                        aria-label="Open AI chat"
                                                    >
                                                        <MessageSquareText className="h-4 w-4" />
                                                    </Button>
                                                </TooltipTrigger>
                                                <TooltipContent side="bottom" className="text-xs">
                                                    Open AI chat
                                                </TooltipContent>
                                            </Tooltip>
                                        </div>
                                    </TooltipProvider>
                                </div>
                            ) : null}
                        </CardHeader>
                    <CardContent 
                        className={cn(
                            // Give charts/tables more room; keep KPI readable
                            "flex-1 overflow-auto widget-content relative",
                            widget.type === "kpi" ? "p-5" : "p-4",
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
                                            {widget.data?.placeholderMode === "auto"
                                                ? "Generating this widget…"
                                                : <>This widget comes to life with your data — ask AI to configure. <span className="font-medium">Double click.</span></>}
                                        </p>
                                    </div>
                                ) : (
                                    <div className="flex flex-col items-center justify-center gap-1">
                                        {/* Subtle blue glow behind the KPI value */}
                                        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                                            <div className="h-28 w-28 rounded-full bg-[#1e3a5f]/10 blur-2xl" />
                                        </div>

                                        <div className="relative">
                                            {/* KPI "hero" number: single-tone night-blue, crisp + premium */}
                                            <div className="text-[44px] leading-[1.0] font-semibold tracking-tight tabular-nums text-[#1e3a5f] drop-shadow-[0_10px_22px_rgba(30,58,95,0.10)]">
                                                {kpiValue}
                                            </div>
                                        </div>
                                        {widget.data?.question ? (
                                            <div className="mt-2 text-[11px] text-slate-500/90 line-clamp-2 max-w-[260px]">
                                                {String(widget.data.question)}
                                            </div>
                                        ) : null}
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
                                                    {widget.data?.placeholderMode === "auto"
                                                        ? "Generating this widget…"
                                                        : <>This widget comes to life with your data — ask AI to configure. <span className="font-medium">Double click.</span></>}
                                                </p>
                                            </div>
                                        </div>
                                    ) : (
                                        <ChartWidget 
                                            chartType={widget.data?.type || 'bar'}
                                            data={widget.data?.data}
                                            labels={widget.data?.labels}
                                            series={widget.data?.series}
                                            mapping={widget.data?.mapping}
                                        />
                                    )}
                                </div>
                            )}
                        {widget.type === 'table' && (
                            <div className="w-full h-full flex flex-col">
                                {isPlaceholder ? (
                                    <div className="w-full h-full flex items-center justify-center px-4 py-6">
                                        <div className="flex flex-col items-center justify-center gap-3">
                                            <Sparkles className="w-8 h-8 text-muted-foreground/40" />
                                            <p className="text-sm text-muted-foreground/70 leading-relaxed max-w-[260px] text-center">
                                                {widget.data?.placeholderMode === "auto"
                                                    ? "Generating this widget…"
                                                    : <>This widget comes to life with your data — ask AI to configure. <span className="font-medium">Double click.</span></>}
                                            </p>
                                        </div>
                                    </div>
                                ) : tableModel.columns.length === 0 ? (
                                    <div className="w-full h-full flex items-center justify-center text-sm text-muted-foreground">
                                        No rows yet.
                                    </div>
                                ) : (
                                    <div className="w-full h-full overflow-auto rounded-md border border-slate-200">
                                        <table className="min-w-full text-xs">
                                            <thead className="sticky top-0 bg-primary text-primary-foreground border-b border-primary/20 shadow-sm">
                                                <tr>
                                                    {tableModel.columns.map((c) => (
                                                        <th
                                                            key={c}
                                                            className="text-left font-semibold px-3 py-2 whitespace-nowrap tracking-wide"
                                                        >
                                                            {c}
                                                        </th>
                                                    ))}
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {tableModel.rows.map((row, idx) => (
                                                    <tr
                                                        key={idx}
                                                        className={cn(
                                                            "border-b border-slate-100",
                                                            // subtle blue zebra rows (readable + premium)
                                                            idx % 2 === 0 ? "bg-blue-50/60" : "bg-sky-50/30",
                                                            "hover:bg-blue-100/45 transition-colors"
                                                        )}
                                                    >
                                                        {tableModel.columns.map((c) => (
                                                            <td key={c} className="px-3 py-2 text-slate-900 whitespace-nowrap">
                                                                {row?.[c] == null ? "—" : String(row[c])}
                                                            </td>
                                                        ))}
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                )}
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

                <Dialog open={isInspectOpen} onOpenChange={setIsInspectOpen}>
                    <DialogContent className="max-w-4xl">
                        <DialogHeader>
                            <DialogTitle className="truncate text-primary">{widget.title}</DialogTitle>
                            <DialogDescription>
                                Inspect data, SQL and details. You can also copy and reuse the query.
                            </DialogDescription>
                        </DialogHeader>

                        <Tabs defaultValue="summary">
                            <TabsList>
                                <TabsTrigger value="summary">Summary</TabsTrigger>
                                <TabsTrigger value="data">Data</TabsTrigger>
                                <TabsTrigger value="sql">SQL</TabsTrigger>
                            </TabsList>

                            <TabsContent value="summary" className="pt-3">
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    <div className="rounded-lg border p-3">
                                        <div className="text-xs text-muted-foreground mb-1">Question</div>
                                        <div className="text-sm">{String(widget.data?.question ?? "—")}</div>
                                    </div>
                                </div>
                                <div className="mt-4 flex gap-2">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => handleCopyToClipboard(String(widget.data?.question ?? ""))}
                                    >
                                        <Copy className="h-4 w-4 mr-2" /> Copy question
                                    </Button>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => openAIChatbox(widget.id, String(widget.data?.question ?? ""), String(widget.data?.answer ?? ""))}
                                    >
                                        <MessageSquareText className="h-4 w-4 mr-2" /> Ask about this
                                    </Button>
                                </div>
                            </TabsContent>

                            <TabsContent value="data" className="pt-3">
                                {Array.isArray(widget.data?.data) && widget.data.data.length > 0 ? (
                                    <div className="rounded-lg border border-slate-200 overflow-auto max-h-[420px]">
                                        <table className="min-w-full text-xs">
                                            <thead className="sticky top-0 bg-primary text-primary-foreground border-b border-primary/20 shadow-sm">
                                                <tr>
                                                    {(Object.keys(widget.data.data[0] || {}) as string[]).slice(0, 12).map((c) => (
                                                        <th key={c} className="text-left font-semibold px-3 py-2 whitespace-nowrap tracking-wide">
                                                            {c}
                                                        </th>
                                                    ))}
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {widget.data.data.slice(0, 50).map((row: any, idx: number) => (
                                                    <tr
                                                        key={idx}
                                                        className={cn(
                                                            "border-b border-slate-100",
                                                            idx % 2 === 0 ? "bg-blue-50/60" : "bg-sky-50/30",
                                                            "hover:bg-blue-100/45 transition-colors"
                                                        )}
                                                    >
                                                        {(Object.keys(widget.data.data[0] || {}) as string[]).slice(0, 12).map((c) => (
                                                            <td key={c} className="px-3 py-2 text-slate-900 whitespace-nowrap">
                                                                {row?.[c] == null ? "—" : String(row[c])}
                                                            </td>
                                                        ))}
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                ) : (
                                    <div className="rounded-lg border p-6 text-sm text-muted-foreground flex items-center gap-2">
                                        <Table2 className="h-4 w-4" /> No rows available for this widget yet.
                                    </div>
                                )}
                            </TabsContent>

                            <TabsContent value="sql" className="pt-3">
                                <div className="flex gap-2 mb-3">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => handleCopyToClipboard(String(widget.data?.sql ?? ""))}
                                    >
                                        <Copy className="h-4 w-4 mr-2" /> Copy SQL
                                    </Button>
                                </div>
                                <pre className="rounded-lg border bg-muted/20 p-3 text-xs overflow-auto max-h-[420px]">
                                    <code>{String(widget.data?.sql ?? "—")}</code>
                                </pre>
                            </TabsContent>
                        </Tabs>
                    </DialogContent>
                </Dialog>
                </>
            )}
        </Rnd>
        </motion.div>
    )
}

// Memoize the component to prevent unnecessary re-renders
export const WidgetContainer = memo(WidgetContainerComponent, (prevProps, nextProps) => {
    // Custom comparison function for better performance
    return (
        prevProps.widget.id === nextProps.widget.id &&
        prevProps.widget.position?.x === nextProps.widget.position?.x &&
        prevProps.widget.position?.y === nextProps.widget.position?.y &&
        prevProps.widget.size?.width === nextProps.widget.size?.width &&
        prevProps.widget.size?.height === nextProps.widget.size?.height &&
        prevProps.widget.type === nextProps.widget.type &&
        prevProps.widget.title === nextProps.widget.title &&
        JSON.stringify(prevProps.widget.data) === JSON.stringify(nextProps.widget.data)
    )
})
