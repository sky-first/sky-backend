"use client"

import { useState, useEffect, useRef } from "react"
import { useWidgetStore } from "@/store/widget-store"
import { useCanvasStore } from "@/store/canvas-store"
import { useAIChatboxStore } from "@/store/ai-chatbox-store"
import { Send, Mic, X, MessageSquare, Database, Settings, FileCode, Maximize2, Minimize2, Copy, ThumbsUp, ThumbsDown, Share2, RefreshCw, Sparkles, BarChart3, PieChart, TrendingUp, Table, Activity } from "lucide-react"
import { motion, AnimatePresence } from "framer-motion"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

interface ChatMessage {
    id: string
    type: "user" | "assistant"
    content: string
    timestamp: Date
}

type MainTab = "chat" | "data" | "configure" | "pipeline"

export function AISearchBar() {
    const [question, setQuestion] = useState("")
    const [isExpanded, setIsExpanded] = useState(false)
    const [isMaximized, setIsMaximized] = useState(false)
    const [hasMessages, setHasMessages] = useState(false)
    const [showScrollbar, setShowScrollbar] = useState(false)
    const [openWidgetMenu, setOpenWidgetMenu] = useState<string | null>(null)
    const [mainTab, setMainTab] = useState<MainTab>("chat")
    const [flyingComet, setFlyingComet] = useState<{
        messageId: string
        startPos: { x: number; y: number }
        endPos: { x: number; y: number }
        widgetType: string
        widgetData: any
        isLanding?: boolean
        movementAngle?: number
    } | null>(null)
    const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
    const [currentWidgetId, setCurrentWidgetId] = useState<string | null>(null)
    const [configureData, setConfigureData] = useState({
        question: "",
        description: "",
        instructions: "",
        responseFormat: "text",
        creativity: 50,
        length: 50,
        knowledge: [] as string[],
        sqlInstructions: "",
    })
    const [finalSQL, setFinalSQL] = useState("-- Select datasets to generate SQL")
    const chatEndRef = useRef<HTMLDivElement>(null)
    const chatContainerRef = useRef<HTMLDivElement>(null)
    const expandedInputRef = useRef<HTMLInputElement>(null)
    const messageRefs = useRef<Record<string, HTMLDivElement | null>>({})
    
    const { addWidget, widgets } = useWidgetStore()
    const { getViewportCenter, snapPosition, findVisiblePositionInViewport } = useCanvasStore()
    const { shouldOpen, widgetId, initialQuestion, initialAnswer, close } = useAIChatboxStore()
    const widget = currentWidgetId ? widgets.find((w) => w.id === currentWidgetId) : null

    // React to store changes - open chatbox with widget information
    useEffect(() => {
        if (shouldOpen && widgetId && initialQuestion !== null) {
            // Set widget ID
            setCurrentWidgetId(widgetId)
            
            // Expand chatbox
            setIsExpanded(true)
            setMainTab("chat")
            
            // Pre-fill with widget information if available
            if (initialQuestion) {
                // Add question as user message
                const userMessage: ChatMessage = {
                    id: `msg-${Date.now()}`,
                    type: "user",
                    content: initialQuestion,
                    timestamp: new Date(),
                }
                
                // Add answer as assistant message if available
                const messages: ChatMessage[] = [userMessage]
                if (initialAnswer) {
                    const aiMessage: ChatMessage = {
                        id: `ai-${Date.now()}`,
                        type: "assistant",
                        content: initialAnswer,
                        timestamp: new Date(),
                    }
                    messages.push(aiMessage)
                    setHasMessages(true)
                }
                
                setChatMessages(messages)
            }
            
            // Clear the store flag
            close()
            
            // Focus input after expansion
            setTimeout(() => {
                expandedInputRef.current?.focus()
            }, 300)
        }
    }, [shouldOpen, widgetId, initialQuestion, initialAnswer, close])

    // Auto-scroll chat to bottom
    useEffect(() => {
        if (isExpanded && mainTab === "chat" && chatEndRef.current) {
            chatEndRef.current.scrollIntoView({ behavior: "smooth" })
        }
    }, [chatMessages, isExpanded, mainTab])

    // Close widget menu when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (openWidgetMenu && !(event.target as Element).closest('[data-widget-menu]')) {
                setOpenWidgetMenu(null)
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [openWidgetMenu])

    // Update SQL when knowledge changes
    useEffect(() => {
        if (configureData.knowledge.length > 0 && configureData.sqlInstructions) {
            const tables = configureData.knowledge.join(", ")
            setFinalSQL(`-- Generated SQL based on selected datasets: ${tables}\n${configureData.sqlInstructions}`)
        } else if (configureData.knowledge.length > 0) {
            const tables = configureData.knowledge.join(", ")
            setFinalSQL(`SELECT * FROM ${tables} LIMIT 1000;`)
        } else {
            setFinalSQL("-- Select datasets to generate SQL")
        }
    }, [configureData.knowledge, configureData.sqlInstructions])

    const handleSendMessage = async () => {
        if (!question.trim()) return

        const userMessage: ChatMessage = {
            id: `msg-${Date.now()}`,
            type: "user",
            content: question,
            timestamp: new Date(),
        }

        setChatMessages(prev => [...prev, userMessage])
        const messageText = question
        setQuestion("")

        // Expand if not already expanded
        if (!isExpanded) {
            setIsExpanded(true)
        }
        
        // Mark that we have messages (for auto-expansion)
        setHasMessages(true)

        // If no widget exists, create one
        if (!currentWidgetId) {
        const viewportCenter = getViewportCenter()
        const finalPosition = snapPosition(viewportCenter.x, viewportCenter.y)
        
        try {
            const widgetId = await addWidget({
                type: 'kpi',
                title: 'Analysis Result',
                position: finalPosition,
                size: { width: 250, height: 120 },
                data: { 
                    value: '0',
                    change: '0%'
                }
            })
                setCurrentWidgetId(widgetId || null)
            } catch (error) {
                console.error('Error creating widget:', error)
            }
        }

        // Simulate AI response (you can replace this with actual API call)
        setTimeout(() => {
            const aiMessage: ChatMessage = {
                id: `ai-${Date.now()}`,
                type: "assistant",
                content: `Esta é uma resposta gerada para: "${messageText}"\n\nAqui está uma análise detalhada com insights relevantes e recomendações baseadas nos dados disponíveis.`,
                timestamp: new Date(),
            }
            setChatMessages(prev => [...prev, aiMessage])
        }, 1000)
    }

    const handleSubmitQuestion = async (e: React.FormEvent) => {
        e.preventDefault()
        await handleSendMessage()
    }

    const handleClose = () => {
        setIsExpanded(false)
        setIsMaximized(false)
        setHasMessages(false)
    }

    const handleCompactInputClick = () => {
        setIsExpanded(true)
        // Focus on expanded input after expansion
        setTimeout(() => {
            expandedInputRef.current?.focus()
        }, 100)
    }

    const handleToggleMaximize = () => {
        setIsMaximized(prev => !prev)
    }


    const handleCreateWidgetWithAnimation = async (
        messageId: string,
        messageElement: HTMLElement,
        widgetType: 'kpi' | 'chart' | 'table',
        widgetData: any
    ) => {
        // Clear any existing comet animation first
        setFlyingComet(null)
        
        // Capture start position BEFORE closing chatbox (comet icon position)
        // Use a small delay to ensure DOM is stable
        await new Promise(resolve => setTimeout(resolve, 10))
        const messageRect = messageElement.getBoundingClientRect()
        const startPos = {
            x: messageRect.right - 20, // Position of comet icon
            y: messageRect.top + 10
        }

        // Get current canvas state for accurate conversion
        const { position: canvasPosition, scale } = useCanvasStore.getState()
        
        // Calculate visible viewport bounds in canvas coordinates
        const viewportLeft = -canvasPosition.x / scale
        const viewportTop = -canvasPosition.y / scale
        const viewportRight = (window.innerWidth - canvasPosition.x) / scale
        const viewportBottom = (window.innerHeight - canvasPosition.y) / scale
        
        // Account for topbar at top (fixed top-4 = 16px + ~50px height = ~66px total)
        const topbarHeight = 66 / scale
        const topbarTopMargin = topbarHeight + (20 / scale)
        
        // Account for topbar left section - fixed left-4, ~250px width
        const topbarLeftWidth = 250 / scale
        const topbarLeftMargin = topbarLeftWidth + (20 / scale)
        
        // Account for topbar right section - fixed right-4, ~200px width
        const topbarRightWidth = 200 / scale
        const topbarRightMargin = topbarRightWidth + (20 / scale)
        
        // Account for toolbar on left - fixed left-4, ~60px width
        const toolbarWidth = 60 / scale
        const toolbarLeftMargin = toolbarWidth + (20 / scale)
        
        // Account for chatbox at bottom
        const chatboxHeight = 80 / scale
        const usableBottom = viewportBottom - chatboxHeight
        const padding = 20 / scale
        
        // Widget dimensions in canvas coordinates
        const widgetSize = widgetData.size || { width: 250, height: 120 }
        const widgetWidth = widgetSize.width
        const widgetHeight = widgetSize.height
        
        // Margin between widgets
        const widgetMargin = 30 / scale
        
        // Calculate safe area bounds (top of viewport, fully visible)
        const safeTop = Math.max(viewportTop + topbarTopMargin, topbarTopMargin)
        const safeBottom = Math.min(usableBottom - widgetHeight - padding, viewportBottom - widgetHeight - padding)
        const safeLeft = Math.max(viewportLeft + Math.max(topbarLeftMargin, toolbarLeftMargin), Math.max(topbarLeftMargin, toolbarLeftMargin))
        const safeRight = Math.min(viewportRight - topbarRightMargin - widgetWidth - padding, viewportRight - widgetWidth - padding)
        
        // Find empty position in the TOP row of visible viewport
        // Priority: Always place in the top visible area
        const existingWidgets = widgets.map(w => ({ position: w.position, size: w.size }))
        
        // Check for overlaps with existing widgets
        const checkOverlap = (x: number, y: number) => {
            return existingWidgets.some(widget => {
                const wx = widget.position.x
                const wy = widget.position.y
                const ww = widget.size.width
                const wh = widget.size.height
                
                const hasHorizontalOverlap = x + widgetWidth + widgetMargin > wx && x - widgetMargin < wx + ww
                const hasVerticalOverlap = y + widgetHeight + widgetMargin > wy && y - widgetMargin < wy + wh
                
                return hasHorizontalOverlap && hasVerticalOverlap
            })
        }
        
        // Strategy: Always place widget in the TOP visible area of viewport
        // Priority: Use safeTop (top of visible viewport) as the Y position
        let finalPosition = { x: safeLeft, y: safeTop }
        
        if (existingWidgets.length > 0) {
            // Find widgets in the top row (same Y position, with tolerance)
            const topRowY = Math.min(...existingWidgets.map(w => w.position.y))
            const rowTolerance = widgetMargin * 2
            const topRowWidgets = existingWidgets.filter(w => 
                Math.abs(w.position.y - topRowY) < rowTolerance
            )
            
            // Check if top row is at or near safeTop (top of visible viewport)
            const isTopRowAtSafeTop = topRowY <= safeTop + rowTolerance
            
            if (topRowWidgets.length > 0 && isTopRowAtSafeTop) {
                // Top row is at the top of viewport - place next to rightmost widget
                const rightmostWidget = topRowWidgets.reduce((rightmost, widget) => {
                    const rightmostRight = rightmost.position.x + rightmost.size.width
                    const widgetRight = widget.position.x + widget.size.width
                    return widgetRight > rightmostRight ? widget : rightmost
                })
                
                // Try to place next to the rightmost widget in the same row
                const rightmostRight = rightmostWidget.position.x + rightmostWidget.size.width
                const tryX = rightmostRight + widgetMargin
                const tryY = safeTop // Always use safeTop to ensure top placement
                
                // Check if it fits horizontally in the current row
                if (
                    tryX >= safeLeft &&
                    tryX + widgetWidth <= safeRight && 
                    !checkOverlap(tryX, tryY)
                ) {
                    const snapped = snapPosition(tryX, tryY)
                    if (
                        snapped.x >= safeLeft &&
                        snapped.x + widgetWidth <= safeRight &&
                        snapped.y >= safeTop &&
                        !checkOverlap(snapped.x, snapped.y)
                    ) {
                        finalPosition = snapped
                    } else {
                        // If snapped position doesn't work, use top-left
                        finalPosition = snapPosition(safeLeft, safeTop)
                    }
                } else {
                    // If doesn't fit, use top-left of safe area
                    finalPosition = snapPosition(safeLeft, safeTop)
                }
            } else {
                // Top row is not at safeTop, or no top row widgets - use top-left of safe area
                // This ensures widget is always placed at the top visible area
                finalPosition = snapPosition(safeLeft, safeTop)
            }
        } else {
            // No existing widgets, use top-left of safe area
            finalPosition = snapPosition(safeLeft, safeTop)
        }
        
        // Ensure final position is within visible bounds and at top
        // Clamp to ensure widget is fully visible in viewport
        finalPosition.x = Math.max(safeLeft, Math.min(finalPosition.x, safeRight - widgetWidth))
        finalPosition.y = Math.max(safeTop, Math.min(finalPosition.y, safeBottom - widgetHeight))
        
        // Final check: if position overlaps, try to find next available spot at top
        if (checkOverlap(finalPosition.x, finalPosition.y)) {
            // Try moving right in the top row
            let foundPosition = false
            for (let x = safeLeft; x <= safeRight - widgetWidth; x += widgetWidth / 2) {
                const tryY = safeTop
                if (!checkOverlap(x, tryY)) {
                    const snapped = snapPosition(x, tryY)
                    // Clamp snapped position to ensure visibility
                    const clampedX = Math.max(safeLeft, Math.min(snapped.x, safeRight - widgetWidth))
                    const clampedY = Math.max(safeTop, Math.min(snapped.y, safeBottom - widgetHeight))
                    if (!checkOverlap(clampedX, clampedY)) {
                        finalPosition = { x: clampedX, y: clampedY }
                        foundPosition = true
                        break
                    }
                }
            }
            // If still no position found, use top-left anyway (will be visible)
            if (!foundPosition) {
                const snapped = snapPosition(safeLeft, safeTop)
                finalPosition.x = Math.max(safeLeft, Math.min(snapped.x, safeRight - widgetWidth))
                finalPosition.y = Math.max(safeTop, Math.min(snapped.y, safeBottom - widgetHeight))
            }
        }
        
        // Calculate widget center in canvas coordinates
        const widgetCenterX = finalPosition.x + widgetSize.width / 2
        const widgetCenterY = finalPosition.y + widgetSize.height / 2
        
        // Calculate end position (widget center) in screen coordinates for animation
        const endPos = {
            x: widgetCenterX * scale + canvasPosition.x,
            y: widgetCenterY * scale + canvasPosition.y
        }

        // Calculate movement angle for comet rotation (comet tail should point opposite to movement)
        const dx = endPos.x - startPos.x
        const dy = endPos.y - startPos.y
        const movementAngle = Math.atan2(dy, dx) * 180 / Math.PI

        // Close menu first
        setOpenWidgetMenu(null)

        // Close chatbox to initial state (before it was clicked)
        setIsExpanded(false)
        setIsMaximized(false)
        setHasMessages(false)

        // Wait for chatbox closing animation to complete (0.3s)
        setTimeout(() => {
            // Ensure we have fresh canvas state when starting animation
            const currentCanvasState = useCanvasStore.getState()
            const currentEndPos = {
                x: widgetCenterX * currentCanvasState.scale + currentCanvasState.position.x,
                y: widgetCenterY * currentCanvasState.scale + currentCanvasState.position.y
            }
            
            // Recalculate angle with current positions
            const currentDx = currentEndPos.x - startPos.x
            const currentDy = currentEndPos.y - startPos.y
            const currentMovementAngle = Math.atan2(currentDy, currentDx) * 180 / Math.PI
            
            // Start comet animation after chatbox is closed with fresh values
            setFlyingComet({
                messageId: `${messageId}-${Date.now()}`, // Unique ID for each animation
                startPos,
                endPos: currentEndPos,
                widgetType,
                widgetData: { ...widgetData, position: finalPosition },
                isLanding: false,
                movementAngle: currentMovementAngle
            })

            // After comet reaches destination, show landing animation, then create widget
            setTimeout(() => {
                // Start landing animation (expansion)
                setFlyingComet(prev => prev ? { ...prev, isLanding: true } : null)
                
                // After landing animation completes, clear comet and create widget
                setTimeout(async () => {
                    // Clear comet first
                    setFlyingComet(null)
                    
                    // Small delay before creating widget to allow comet to fade out
                    setTimeout(async () => {
                        try {
                            await addWidget({
                                type: widgetType,
                                ...widgetData,
                                position: finalPosition
                            })
        } catch (error) {
            console.error('Error creating widget:', error)
        }
                    }, 100) // Small delay for smooth transition
                }, 400) // Landing animation duration
            }, 600) // Travel animation duration
        }, 300) // Chatbox closing animation duration
    }


    return (
        <>
            {/* Flying Comet Animation */}
            <AnimatePresence>
                {flyingComet && (
                    <motion.div
                        initial={{ 
                            x: flyingComet.startPos.x,
                            y: flyingComet.startPos.y,
                            scale: 1,
                            opacity: 1,
                            rotate: flyingComet.movementAngle ?? 0
                        }}
                        animate={flyingComet.isLanding ? {
                            x: flyingComet.endPos.x,
                            y: flyingComet.endPos.y,
                            scale: [1.2, 3, 0],
                            opacity: [1, 0.8, 0],
                            rotate: flyingComet.movementAngle ?? 0
                        } : {
                            x: flyingComet.endPos.x,
                            y: flyingComet.endPos.y,
                            scale: 1.2,
                            opacity: 1,
                            rotate: flyingComet.movementAngle ?? 0
                        }}
                        exit={{ 
                            scale: 0,
                            opacity: 0
                        }}
                        transition={flyingComet.isLanding ? {
                            duration: 0.4,
                            ease: "easeOut",
                            times: [0, 0.5, 1]
                        } : {
                            duration: 0.6,
                            ease: "easeInOut"
                        }}
                        className="fixed pointer-events-none z-[100]"
                        style={{
                            transform: 'translate(-50%, -50%)'
                        }}
                    >
                        {/* Comet visual: circle with tail */}
                        <svg
                            width="48"
                            height="48"
                            viewBox="0 0 48 48"
                            className="drop-shadow-lg"
                            style={{ filter: 'drop-shadow(0 0 12px rgba(59, 130, 246, 0.8))' }}
                        >
                            <defs>
                                <linearGradient id={`cometTail-${flyingComet.messageId}`} x1="100%" y1="50%" x2="0%" y2="50%">
                                    <stop offset="0%" stopColor="rgba(59, 130, 246, 0.9)" stopOpacity="0.9" />
                                    <stop offset="30%" stopColor="rgba(59, 130, 246, 0.6)" stopOpacity="0.6" />
                                    <stop offset="70%" stopColor="rgba(147, 197, 253, 0.3)" stopOpacity="0.3" />
                                    <stop offset="100%" stopColor="rgba(147, 197, 253, 0)" stopOpacity="0" />
                                </linearGradient>
                                <radialGradient id={`cometGlow-${flyingComet.messageId}`} cx="50%" cy="50%">
                                    <stop offset="0%" stopColor="rgb(147, 197, 253)" stopOpacity="1" />
                                    <stop offset="70%" stopColor="rgb(59, 130, 246)" stopOpacity="0.8" />
                                    <stop offset="100%" stopColor="rgb(59, 130, 246)" stopOpacity="0.4" />
                                </radialGradient>
                            </defs>
                            {/* Long tail path - pointing backwards (opposite to movement direction) */}
                            {/* Tail starts from center and extends backwards */}
                            <path
                                d="M 24 24 L 8 24"
                                stroke={`url(#cometTail-${flyingComet.messageId})`}
                                strokeWidth="4"
                                fill="none"
                                strokeLinecap="round"
                            />
                            {/* Secondary tail for depth */}
                            <path
                                d="M 24 24 L 10 24"
                                stroke={`url(#cometTail-${flyingComet.messageId})`}
                                strokeWidth="2"
                                fill="none"
                                strokeLinecap="round"
                                opacity="0.5"
                            />
                            {/* Circle (comet head) - positioned at center */}
                            <circle
                                cx="24"
                                cy="24"
                                r="7"
                                fill={`url(#cometGlow-${flyingComet.messageId})`}
                            />
                            {/* Bright center */}
                            <circle
                                cx="24"
                                cy="24"
                                r="4"
                                fill="rgb(191, 219, 254)"
                            />
                            {/* Core highlight */}
                            <circle
                                cx="24"
                                cy="24"
                                r="2"
                                fill="rgb(255, 255, 255)"
                            />
                        </svg>
                    </motion.div>
                )}
            </AnimatePresence>

            <div 
                className="fixed bottom-16 left-1/2 transform -translate-x-1/2 z-10 pointer-events-auto" 
                data-tour="ai-search"
                style={{ 
                    // Garantir que sempre fique fixo na parte inferior
                    bottom: '64px'
                }}
            >
            <AnimatePresence mode="wait">
                {!isExpanded ? (
                    // Compact view - just the input bar
                    <motion.div
                        key="compact"
                        initial={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.2 }}
                    >
            <form
                onSubmit={handleSubmitQuestion}
                            onClick={handleCompactInputClick}
                            className="rounded-full px-6 py-3 flex items-center gap-3 min-w-[500px] max-w-[600px] border-2 border-border bg-background/95 backdrop-blur-xl shadow-lg cursor-text"
            >
                <input
                    type="text"
                    placeholder="What you want to analyse today?"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault()
                            handleSubmitQuestion(e as any)
                        }
                    }}
                                onClick={(e) => {
                                    e.stopPropagation()
                                    handleCompactInputClick()
                                }}
                                className="flex-1 bg-transparent text-foreground placeholder:text-muted-foreground outline-none text-sm font-medium cursor-text"
                />
                <button 
                    type="button"
                    className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-full hover:bg-accent"
                    aria-label="Voice input"
                >
                    <Mic className="h-5 w-5" />
                </button>
                <button 
                    type="submit" 
                    className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-full hover:bg-accent"
                    aria-label="Submit question"
                >
                    <Send className="h-5 w-5" />
                </button>
            </form>
                    </motion.div>
                ) : (
                    // Expanded view - chat area + input (expande para cima)
                    <motion.div
                        key="expanded"
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: 20 }}
                        transition={{ duration: 0.3, ease: "easeOut" }}
                        className="bg-background/95 backdrop-blur-xl border-2 border-border rounded-2xl shadow-2xl flex flex-col"
                        style={{ 
                            width: isMaximized 
                                ? "50vw" 
                                : hasMessages 
                                    ? "660px" // 600px + 10% = 660px quando tem mensagens
                                    : "600px", // Tamanho inicial
                            maxWidth: isMaximized ? "50vw" : "90vw",
                            maxHeight: isMaximized 
                                ? "620px" 
                                : hasMessages 
                                    ? "531px" // 462px + 15% = 531px quando tem mensagens
                                    : "520px", // Aumentado para acomodar margens e pergunta adicional
                            height: "auto",
                            // Garantir que a parte inferior sempre fique fixa
                            marginBottom: 0,
                            transition: "max-height 0.3s ease-out, width 0.3s ease-out"
                        }}
                    >
                        {/* Header */}
                        <div className="px-4 py-3 border-b border-border/50 flex items-center justify-between flex-shrink-0">
                            <div className="flex items-center gap-2">
                                {/* Tab Icons */}
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <button
                                            onClick={() => setMainTab("chat")}
                                            className={cn(
                                                "p-2 rounded-lg transition-colors",
                                                mainTab === "chat"
                                                    ? "bg-primary text-primary-foreground"
                                                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                                            )}
                                            aria-label="Chat"
                                        >
                                            <MessageSquare className="h-4 w-4" />
                                        </button>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" className="text-xs">
                                        Chat
                                    </TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <button
                                            onClick={() => setMainTab("data")}
                                            className={cn(
                                                "p-2 rounded-lg transition-colors",
                                                mainTab === "data"
                                                    ? "bg-primary text-primary-foreground"
                                                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                                            )}
                                            aria-label="Data"
                                        >
                                            <Database className="h-4 w-4" />
                                        </button>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" className="text-xs">
                                        Data
                                    </TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <button
                                            onClick={() => setMainTab("configure")}
                                            className={cn(
                                                "p-2 rounded-lg transition-colors",
                                                mainTab === "configure"
                                                    ? "bg-primary text-primary-foreground"
                                                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                                            )}
                                            aria-label="Configure"
                                        >
                                            <Settings className="h-4 w-4" />
                                        </button>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" className="text-xs">
                                        Configure
                                    </TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <button
                                            onClick={() => setMainTab("pipeline")}
                                            className={cn(
                                                "p-2 rounded-lg transition-colors",
                                                mainTab === "pipeline"
                                                    ? "bg-primary text-primary-foreground"
                                                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                                            )}
                                            aria-label="Pipeline"
                                        >
                                            <FileCode className="h-4 w-4" />
                                        </button>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" className="text-xs">
                                        Pipeline
                                    </TooltipContent>
                                </Tooltip>
                            </div>
                            <div className="flex items-center gap-1">
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <button
                                            onClick={handleToggleMaximize}
                                            className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-full hover:bg-accent"
                                            aria-label={isMaximized ? "Minimize" : "Expand"}
                                        >
                                            {isMaximized ? (
                                                <Minimize2 className="h-4 w-4" />
                                            ) : (
                                                <Maximize2 className="h-4 w-4" />
                                            )}
                                        </button>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" className="text-xs">
                                        {isMaximized ? "Minimizar" : "Expandir"}
                                    </TooltipContent>
                                </Tooltip>
                                <button
                                    onClick={handleClose}
                                    className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-full hover:bg-accent"
                                    aria-label="Close chat"
                                >
                                    <X className="h-4 w-4" />
                                </button>
                            </div>
                        </div>

                        {/* Content area - changes based on selected tab */}
                        <div
                            ref={chatContainerRef}
                            onMouseEnter={() => setShowScrollbar(true)}
                            onMouseLeave={() => setShowScrollbar(false)}
                            onWheel={(e) => {
                                // Prevent canvas scroll when scrolling inside chatbox
                                e.stopPropagation()
                            }}
                            className={cn(
                                "flex-1 overflow-y-auto min-h-0",
                                "transition-all duration-200",
                                showScrollbar ? "custom-scrollbar-visible" : "custom-scrollbar-hidden"
                            )}
                            style={{ 
                                maxHeight: isMaximized 
                                    ? "520px" 
                                    : hasMessages 
                                        ? "431px" // Ajustado proporcionalmente (362px + 15% ≈ 416px, ajustado para 431px)
                                        : "343px", // 285px + 15% ≈ 328px, ajustado para 343px para manter proporção
                                transition: "max-height 0.3s ease-out"
                            }}
                        >
                            {/* CHAT TAB */}
                            {mainTab === "chat" && (
                                <div className="px-4 py-3 space-y-3">
                                    {chatMessages.length === 0 ? (
                                        <div className="space-y-2">
                                            {/* Intro text */}
                                            <div className="text-center pt-6">
                                                <p className="text-xs font-medium text-foreground">Some suggestions.</p>
                                            </div>
                                            
                                            {/* Suggestion Cards Grid 2x2 */}
                                            <div className="grid grid-cols-2 gap-3 max-w-[40%] mx-auto mb-8">
                                                {[
                                                    "How much orders yesterday?",
                                                    "When is the release 5 of...",
                                                    "Give me a chart where I see...",
                                                    "How many meetings this week?"
                                                ].map((suggestion, idx) => {
                                                    return (
                                                        <Tooltip key={idx}>
                                                            <TooltipTrigger asChild>
                                                                <button
                                                                    onClick={async () => {
                                                                        const userMessage: ChatMessage = {
                                                                            id: `msg-${Date.now()}`,
                                                                            type: "user",
                                                                            content: suggestion,
                                                                            timestamp: new Date(),
                                                                        }
                                                                        setChatMessages(prev => [...prev, userMessage])
                                                                        setQuestion("")
                                                                        setHasMessages(true)
                                                                        
                                                                        // If no widget exists, create one
                                                                        if (!currentWidgetId) {
                                                                            const viewportCenter = getViewportCenter()
                                                                            const finalPosition = snapPosition(viewportCenter.x, viewportCenter.y)
                                                                            try {
                                                                                const widgetId = await addWidget({
                                                                                    type: 'kpi',
                                                                                    title: 'Analysis Result',
                                                                                    position: finalPosition,
                                                                                    size: { width: 250, height: 120 },
                                                                                    data: { 
                                                                                        value: '0',
                                                                                        change: '0%'
                                                                                    }
                                                                                })
                                                                                setCurrentWidgetId(widgetId || null)
                                                                            } catch (error) {
                                                                                console.error('Error creating widget:', error)
                                                                            }
                                                                        }
                                                                        
                                                                        // Simulate AI response
                                                                        setTimeout(() => {
                                                                            const aiMessage: ChatMessage = {
                                                                                id: `ai-${Date.now()}`,
                                                                                type: "assistant",
                                                                                content: `Esta é uma resposta gerada para: "${suggestion}"\n\nAqui está uma análise detalhada com insights relevantes e recomendações baseadas nos dados disponíveis.`,
                                                                                timestamp: new Date(),
                                                                            }
                                                                            setChatMessages(prev => [...prev, aiMessage])
                                                                        }, 1000)
                                                                    }}
                                                                    className={cn(
                                                                        "group relative p-3 rounded-3xl",
                                                                        "bg-gradient-to-br from-slate-50 to-gray-50 dark:from-slate-800 dark:to-gray-900",
                                                                        "border border-slate-200/60 dark:border-slate-700/60",
                                                                        "shadow-sm hover:shadow-lg hover:shadow-slate-200/50 dark:hover:shadow-slate-900/50",
                                                                        "hover:scale-[1.02] active:scale-[0.98]",
                                                                        "hover:border-slate-300 dark:hover:border-slate-600",
                                                                        "transition-all duration-200 ease-out",
                                                                        "flex items-center justify-center",
                                                                        "min-h-[70px]",
                                                                        "overflow-hidden"
                                                                    )}
                                                                >
                                                                    {/* Subtle gradient overlay on hover */}
                                                                    <div className="absolute inset-0 rounded-3xl bg-gradient-to-br from-blue-50/0 to-purple-50/0 group-hover:from-blue-50/30 group-hover:to-purple-50/20 dark:group-hover:from-blue-950/20 dark:group-hover:to-purple-950/10 transition-all duration-200" />
                                                                    
                                                                    {/* Content */}
                                                                    <p className="text-xs font-medium text-slate-700 dark:text-slate-200 text-center leading-relaxed px-2 break-words line-clamp-3 relative z-10">
                                                                        {suggestion}
                                                                    </p>
                                                                </button>
                                                            </TooltipTrigger>
                                                            {/* Tooltip - show full text on hover */}
                                                            <TooltipContent side="top" className="text-xs max-w-[200px]">
                                                                {suggestion}
                                                            </TooltipContent>
                                                        </Tooltip>
                                                    )
                                                })}
                                            </div>
                                            
                                            {/* Question text below cards - styled as AI message */}
                                            <div className="flex justify-start">
                                                <div className="relative max-w-[85%] rounded-2xl px-4 py-3 bg-muted/40 border border-border/50">
                                                    <p className="text-sm text-foreground">How can I help you?</p>
                                                </div>
                                            </div>
                                        </div>
                                    ) : (
                                        chatMessages.map((msg, index) => {
                                            // Check if this message is animating (messageId may have timestamp suffix)
                                            const isAnimating = flyingComet?.messageId?.startsWith(msg.id) ?? false
                                            
                                            return (
                                                <div key={msg.id} className="space-y-2">
                                                    <motion.div
                                                        ref={(el) => {
                                                            if (el) messageRefs.current[msg.id] = el
                                                        }}
                                                        animate={isAnimating ? {
                                                            scale: 0,
                                                            opacity: 0
                                                        } : {
                                                            scale: 1,
                                                            opacity: 1
                                                        }}
                                                        transition={{ duration: 0.3 }}
                                                        className={cn(
                                                            "flex",
                                                            msg.type === "user" ? "justify-end" : "justify-start"
                                                        )}
                                                    >
                                                        <div className={cn(
                                                            "relative max-w-[85%] rounded-2xl px-4 py-3",
                                                            msg.type === "user"
                                                                ? "bg-primary text-primary-foreground"
                                                                : "bg-muted/40 border border-border/50"
                                                        )}>
                                                            {/* Comet icon for assistant messages */}
                                                            {msg.type === "assistant" && !isAnimating && (
                                                                <div className="absolute top-2 right-2 z-10">
                                                                    <Tooltip>
                                                                        <TooltipTrigger asChild>
                                                                            <button
                                                                                data-widget-menu
                                                                                onClick={(e) => {
                                                                                    e.stopPropagation()
                                                                                    setOpenWidgetMenu(openWidgetMenu === msg.id ? null : msg.id)
                                                                                }}
                                                                                className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                                                                                aria-label="Visualize as widget"
                                                                            >
                                                                                <img
                                                                                    src="https://img.icons8.com/external-flaticons-flat-flat-icons/64/external-comet-astrology-flaticons-flat-flat-icons.png"
                                                                                    alt="comet"
                                                                                    width="27"
                                                                                    height="27"
                                                                                    className="h-7 w-7"
                                                                                />
                                                                            </button>
                                                                        </TooltipTrigger>
                                                                        <TooltipContent side="top" className="text-[10px] px-1.5 py-0.5">
                                                                            Widget comet
                                                                        </TooltipContent>
                                                                    </Tooltip>
                                                                    
                                                                    {/* Widget Menu - Small lateral menu to the right */}
                                                                    <AnimatePresence>
                                                                        {openWidgetMenu === msg.id && (
                                                                            <motion.div 
                                                                                initial={{ opacity: 0, scale: 0.95, x: -10 }}
                                                                                animate={{ opacity: 1, scale: 1, x: 0 }}
                                                                                exit={{ opacity: 0, scale: 0.95, x: -10 }}
                                                                                transition={{ duration: 0.15 }}
                                                                                className="absolute top-0 left-full ml-1.5 bg-background/95 backdrop-blur-sm border border-border/50 rounded-md shadow-md z-30 w-[110px]"
                                                                                data-widget-menu
                                                                            >
                                                                            <div className="py-0.5">
                                                                                <button
                                                                                    onClick={() => {
                                                                                        const messageElement = messageRefs.current[msg.id]
                                                                                        if (messageElement) {
                                                                                            handleCreateWidgetWithAnimation(
                                                                                                msg.id,
                                                                                                messageElement,
                                                                                                'kpi',
                                                                                                {
                                                                                                    title: 'AI Response',
                                                                                                    size: { width: 250, height: 120 },
                                                                                                    data: { 
                                                                                                        value: msg.content.substring(0, 50),
                                                                                                        change: '0%'
                                                                                                    }
                                                                                                }
                                                                                            )
                                                                                        }
                                                                                    }}
                                                                                    className="w-full flex items-center gap-1.5 px-2 py-1 hover:bg-accent/50 transition-colors text-[11px] text-left text-muted-foreground hover:text-foreground"
                                                                                >
                                                                                    <BarChart3 className="h-3 w-3 flex-shrink-0" />
                                                                                    <span className="truncate">KPI</span>
                                                                                </button>
                                                                                
                                                                                <div className="h-px bg-border/50 my-0.5 mx-1.5" />
                                                                                
                                                                                {[
                                                                                    { type: 'bar', label: 'Bar', icon: BarChart3 },
                                                                                    { type: 'pie', label: 'Pie', icon: PieChart },
                                                                                    { type: 'line', label: 'Line', icon: TrendingUp },
                                                                                    { type: 'scatter', label: 'Scatter', icon: Activity }
                                                                                ].map((chart) => {
                                                                                    const Icon = chart.icon
                                                                                    return (
                                                                                        <button
                                                                                            key={chart.type}
                                                                                            onClick={() => {
                                                                                                const messageElement = messageRefs.current[msg.id]
                                                                                                if (messageElement) {
                                                                                                    handleCreateWidgetWithAnimation(
                                                                                                        msg.id,
                                                                                                        messageElement,
                                                                                                        'chart',
                                                                                                        {
                                                                                                            title: `${chart.label} Chart`,
                                                                                                            size: { width: 320, height: 240 },
                                                                                                            data: {
                                                                                                                type: chart.type,
                                                                                                                series: [0, 0, 0, 0, 0],
                                                                                                                labels: ['A', 'B', 'C', 'D', 'E'],
                                                                                                            }
                                                                                                        }
                                                                                                    )
                                                                                                }
                                                                                            }}
                                                                                            className="w-full flex items-center gap-1.5 px-2 py-1 hover:bg-accent/50 transition-colors text-[11px] text-left text-muted-foreground hover:text-foreground"
                                                                                        >
                                                                                            <Icon className="h-3 w-3 flex-shrink-0" />
                                                                                            <span className="truncate">{chart.label}</span>
                                                                                        </button>
                                                                                    )
                                                                                })}
                                                                                
                                                                                <div className="h-px bg-border/50 my-0.5 mx-1.5" />
                                                                                
                                                                                <button
                                                                                    onClick={() => {
                                                                                        const messageElement = messageRefs.current[msg.id]
                                                                                        if (messageElement) {
                                                                                            handleCreateWidgetWithAnimation(
                                                                                                msg.id,
                                                                                                messageElement,
                                                                                                'table',
                                                                                                {
                                                                                                    title: 'AI Response Table',
                                                                                                    size: { width: 400, height: 250 },
                                                                                                    data: {
                                                                                                        columns: ['Column 1', 'Column 2', 'Column 3'],
                                                                                                        rows: [
                                                                                                            ['Data 1', 'Data 2', 'Data 3'],
                                                                                                            ['Data 4', 'Data 5', 'Data 6']
                                                                                                        ]
                                                                                                    }
                                                                                                }
                                                                                            )
                                                                                        }
                                                                                    }}
                                                                                    className="w-full flex items-center gap-1.5 px-2 py-1 hover:bg-accent/50 transition-colors text-[11px] text-left text-muted-foreground hover:text-foreground"
                                                                                >
                                                                                    <Table className="h-3 w-3 flex-shrink-0" />
                                                                                    <span className="truncate">Table</span>
                                                                                </button>
                                                                            </div>
                                                                            </motion.div>
                                                                        )}
                                                                    </AnimatePresence>
                                                                </div>
                                                            )}
                                                            <p className="text-sm whitespace-pre-wrap leading-relaxed pr-8">
                                                                {msg.content}
                                                            </p>
                                                        </div>
                                                    </motion.div>
                                                    
                                                    {/* Action Icons - only show for assistant messages */}
                                                    {msg.type === "assistant" && (
                                                        <div className="flex items-center gap-1 px-1">
                                                            <Tooltip>
                                                                <TooltipTrigger asChild>
                                                                    <button
                                                                        onClick={() => {
                                                                            navigator.clipboard.writeText(msg.content)
                                                                        }}
                                                                        className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                                                                        aria-label="Copy"
                                                                    >
                                                                        <Copy className="h-4 w-4" />
                                                                    </button>
                                                                </TooltipTrigger>
                                                                <TooltipContent side="top" className="text-xs">
                                                                    Copy
                                                                </TooltipContent>
                                                            </Tooltip>
                                                            
                                                            <Tooltip>
                                                                <TooltipTrigger asChild>
                                                                    <button
                                                                        onClick={() => {
                                                                            console.log("Good response:", msg.id)
                                                                        }}
                                                                        className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                                                                        aria-label="Good response"
                                                                    >
                                                                        <ThumbsUp className="h-4 w-4" />
                                                                    </button>
                                                                </TooltipTrigger>
                                                                <TooltipContent side="top" className="text-xs">
                                                                    Good response
                                                                </TooltipContent>
                                                            </Tooltip>
                                                            
                                                            <Tooltip>
                                                                <TooltipTrigger asChild>
                                                                    <button
                                                                        onClick={() => {
                                                                            console.log("Bad response:", msg.id)
                                                                        }}
                                                                        className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                                                                        aria-label="Bad response"
                                                                    >
                                                                        <ThumbsDown className="h-4 w-4" />
                                                                    </button>
                                                                </TooltipTrigger>
                                                                <TooltipContent side="top" className="text-xs">
                                                                    Bad response
                                                                </TooltipContent>
                                                            </Tooltip>
                                                            
                                                            <Tooltip>
                                                                <TooltipTrigger asChild>
                                                                    <button
                                                                        onClick={() => {
                                                                            console.log("Share:", msg.id)
                                                                        }}
                                                                        className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                                                                        aria-label="Share"
                                                                    >
                                                                        <Share2 className="h-4 w-4" />
                                                                    </button>
                                                                </TooltipTrigger>
                                                                <TooltipContent side="top" className="text-xs">
                                                                    Share
                                                                </TooltipContent>
                                                            </Tooltip>
                                                            
                                                            <Tooltip>
                                                                <TooltipTrigger asChild>
                                                                    <button
                                                                        onClick={() => {
                                                                            console.log("Try again:", msg.id)
                                                                        }}
                                                                        className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                                                                        aria-label="Try again"
                                                                    >
                                                                        <RefreshCw className="h-4 w-4" />
                                                                    </button>
                                                                </TooltipTrigger>
                                                                <TooltipContent side="top" className="text-xs">
                                                                    Try again
                                                                </TooltipContent>
                                                            </Tooltip>
                                                        </div>
                                                    )}
                                                </div>
                                            )
                                        })
                                    )}
                                    <div ref={chatEndRef} />
                                </div>
                            )}

                            {/* DATA TAB */}
                            {mainTab === "data" && (
                                <div className="px-4 py-3 space-y-4">
                                    <div className="space-y-3">
                                        <Label className="text-sm font-semibold">Knowledge (Datasets)</Label>
                                        <p className="text-xs text-muted-foreground">
                                            Select tables, files, or data sources to use for this query.
                                        </p>
                                        <div className="border rounded-lg divide-y divide-border overflow-hidden">
                                            <div className="px-3 py-2 flex items-center justify-between text-xs hover:bg-muted/30 transition-colors">
                                                <div className="flex flex-col">
                                                    <span className="font-medium">revenue_ledger</span>
                                                    <span className="text-xs text-muted-foreground">
                                                        analytics.revenue_ledger (Table)
                                                    </span>
                                                </div>
                                                <input
                                                    type="checkbox"
                                                    checked={configureData.knowledge.includes("revenue_ledger")}
                                                    onChange={(e) => {
                                                        const knowledge = e.target.checked
                                                            ? [...configureData.knowledge, "revenue_ledger"]
                                                            : configureData.knowledge.filter((k) => k !== "revenue_ledger")
                                                        setConfigureData({ ...configureData, knowledge })
                                                    }}
                                                    className="w-4 h-4 rounded cursor-pointer"
                                                />
                                            </div>
                                            <div className="px-3 py-2 flex items-center justify-between text-xs hover:bg-muted/30 transition-colors">
                                                <div className="flex flex-col">
                                                    <span className="font-medium">billing_invoice</span>
                                                    <span className="text-xs text-muted-foreground">
                                                        teambIue_finance.silver.billing_invoice
                                                    </span>
                                                </div>
                                                <input
                                                    type="checkbox"
                                                    checked={configureData.knowledge.includes("billing_invoice")}
                                                    onChange={(e) => {
                                                        const knowledge = e.target.checked
                                                            ? [...configureData.knowledge, "billing_invoice"]
                                                            : configureData.knowledge.filter((k) => k !== "billing_invoice")
                                                        setConfigureData({ ...configureData, knowledge })
                                                    }}
                                                    className="w-4 h-4 rounded cursor-pointer"
                                                />
                                            </div>
                                            <div className="px-3 py-2 flex items-center justify-between text-xs hover:bg-muted/30 transition-colors">
                                                <div className="flex flex-col">
                                                    <span className="font-medium">customers_dim</span>
                                                    <span className="text-xs text-muted-foreground">
                                                        analytics.customers_dim (View)
                                                    </span>
                                                </div>
                                                <input
                                                    type="checkbox"
                                                    checked={configureData.knowledge.includes("customers_dim")}
                                                    onChange={(e) => {
                                                        const knowledge = e.target.checked
                                                            ? [...configureData.knowledge, "customers_dim"]
                                                            : configureData.knowledge.filter((k) => k !== "customers_dim")
                                                        setConfigureData({ ...configureData, knowledge })
                                                    }}
                                                    className="w-4 h-4 rounded cursor-pointer"
                                                />
                                            </div>
                                        </div>
                                        <Button variant="outline" size="sm" className="w-full rounded-lg text-xs">
                                            + Add Data Source
                                        </Button>
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="sqlInstructions" className="text-sm font-semibold">
                                            Instructions
                                        </Label>
                                        <Textarea
                                            id="sqlInstructions"
                                            value={configureData.sqlInstructions}
                                            onChange={(e) =>
                                                setConfigureData({ ...configureData, sqlInstructions: e.target.value })
                                            }
                                            placeholder="Add specific instructions or constraints..."
                                            className="min-h-[80px] font-mono text-xs rounded-lg"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="finalSQL" className="text-sm font-semibold">
                                            SQL Query
                                        </Label>
                                        <Textarea
                                            id="finalSQL"
                                            value={finalSQL}
                                            onChange={(e) => setFinalSQL(e.target.value)}
                                            placeholder="SQL will be generated here..."
                                            className="min-h-[100px] font-mono text-xs rounded-lg bg-muted/30"
                                        />
                                    </div>
                                </div>
                            )}

                            {/* CONFIGURE TAB */}
                            {mainTab === "configure" && (
                                <div className="px-4 py-3 space-y-4">
                                    <div className="space-y-2">
                                        <Label htmlFor="question" className="text-sm font-medium">
                                            Question
                                        </Label>
                                        <Input
                                            id="question"
                                            value={configureData.question}
                                            onChange={(e) =>
                                                setConfigureData({ ...configureData, question: e.target.value })
                                            }
                                            placeholder="What is the revenue for this month?"
                                            className="rounded-lg text-sm"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="description" className="text-sm font-medium">
                                            Description
                                        </Label>
                                        <Textarea
                                            id="description"
                                            value={configureData.description}
                                            onChange={(e) =>
                                                setConfigureData({ ...configureData, description: e.target.value })
                                            }
                                            placeholder="Add a description for this query..."
                                            className="min-h-[60px] rounded-lg text-sm"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="instructions" className="text-sm font-medium">
                                            Instructions
                                        </Label>
                                        <Textarea
                                            id="instructions"
                                            value={configureData.instructions}
                                            onChange={(e) =>
                                                setConfigureData({ ...configureData, instructions: e.target.value })
                                            }
                                            placeholder="Add general instructions on how you want the AI to behave..."
                                            className="min-h-[100px] font-mono text-xs rounded-lg"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="responseFormat" className="text-sm font-medium">
                                            Response Format
                                        </Label>
                                        <Select
                                            value={configureData.responseFormat}
                                            onValueChange={(value) =>
                                                setConfigureData({ ...configureData, responseFormat: value })
                                            }
                                        >
                                            <SelectTrigger id="responseFormat" className="w-full rounded-lg text-sm">
                                                <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="text">Text</SelectItem>
                                                <SelectItem value="markdown">Markdown</SelectItem>
                                                <SelectItem value="json">JSON</SelectItem>
                                                <SelectItem value="table">Table</SelectItem>
                                                <SelectItem value="chart">Chart</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div className="space-y-3">
                                        <div className="space-y-2">
                                            <div className="flex items-center justify-between">
                                                <Label className="text-sm font-medium">Creativity</Label>
                                                <span className="text-xs text-muted-foreground">{configureData.creativity}%</span>
                                            </div>
                                            <Slider
                                                value={[configureData.creativity]}
                                                onValueChange={(value) =>
                                                    setConfigureData({ ...configureData, creativity: value[0] })
                                                }
                                                min={0}
                                                max={100}
                                                step={1}
                                                className="w-full"
                                            />
                                        </div>
                                        <div className="space-y-2">
                                            <div className="flex items-center justify-between">
                                                <Label className="text-sm font-medium">Length</Label>
                                                <span className="text-xs text-muted-foreground">{configureData.length}%</span>
                                            </div>
                                            <Slider
                                                value={[configureData.length]}
                                                onValueChange={(value) =>
                                                    setConfigureData({ ...configureData, length: value[0] })
                                                }
                                                min={0}
                                                max={100}
                                                step={1}
                                                className="w-full"
                                            />
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* PIPELINE TAB */}
                            {mainTab === "pipeline" && (
                                <div className="px-4 py-3 space-y-3">
                                    <div className="space-y-2">
                                        <h3 className="text-sm font-semibold">Pipeline Execution</h3>
                                        <p className="text-xs text-muted-foreground">
                                            Visualize the step-by-step process of how your question was processed and answered.
                                        </p>
                                    </div>
                                    <div className="space-y-2">
                                        <div className="border rounded-lg p-3 bg-background">
                                            <div className="flex items-center gap-2 mb-2">
                                                <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center">
                                                    <span className="text-xs font-semibold text-primary">1</span>
                                                </div>
                                                <h4 className="font-semibold text-sm">Question</h4>
                                            </div>
                                            <p className="text-xs text-muted-foreground ml-8">
                                                {configureData.question || chatMessages[0]?.content || "No question provided"}
                                            </p>
                                        </div>
                                        <div className="border rounded-lg p-3 bg-background">
                                            <div className="flex items-center gap-2 mb-2">
                                                <div className="w-6 h-6 rounded-full bg-purple-500/20 flex items-center justify-center">
                                                    <Database className="w-3 h-3 text-purple-600 dark:text-purple-400" />
                                                </div>
                                                <h4 className="font-semibold text-sm">Database</h4>
                                            </div>
                                            <p className="text-xs text-muted-foreground ml-8">
                                                {configureData.knowledge.length > 0 
                                                    ? configureData.knowledge.join(", ")
                                                    : "No datasets selected"}
                                            </p>
                                        </div>
                                        <div className="border rounded-lg p-3 bg-background">
                                            <div className="flex items-center gap-2 mb-2">
                                                <div className="w-6 h-6 rounded-full bg-blue-500/20 flex items-center justify-center">
                                                    <FileCode className="w-3 h-3 text-blue-600 dark:text-blue-400" />
                                                </div>
                                                <h4 className="font-semibold text-sm">SQL</h4>
                                            </div>
                                            <p className="text-xs text-muted-foreground ml-8 font-mono">
                                                {finalSQL || "-- Not executed"}
                                            </p>
                                        </div>
                                        <div className="border rounded-lg p-3 bg-background">
                                            <div className="flex items-center gap-2 mb-2">
                                                <div className="w-6 h-6 rounded-full bg-green-500/20 flex items-center justify-center">
                                                    <span className="text-xs font-semibold text-green-600 dark:text-green-400">✓</span>
                                                </div>
                                                <h4 className="font-semibold text-sm">Answer</h4>
                                            </div>
                                            <p className="text-xs text-muted-foreground ml-8">
                                                {chatMessages.length > 0 && chatMessages[chatMessages.length - 1]?.type === "assistant"
                                                    ? chatMessages[chatMessages.length - 1].content
                                                    : "Not executed"}
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Input area - sempre na parte inferior */}
                        <div className="px-4 py-3 border-t border-border/50 flex-shrink-0">
                            <form
                                onSubmit={handleSubmitQuestion}
                                className="flex items-center gap-2"
                            >
                                <div className="flex-1 relative">
                                    <input
                                        ref={expandedInputRef}
                                        type="text"
                                        placeholder="Ask anything..."
                                        value={question}
                                        onChange={(e) => setQuestion(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter' && !e.shiftKey) {
                                                e.preventDefault()
                                                handleSubmitQuestion(e as any)
                                            }
                                        }}
                                        className="w-full px-4 py-2.5 pr-20 bg-muted/50 border border-border rounded-xl text-sm text-foreground placeholder:text-muted-foreground outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/20 transition-all"
                                    />
                                </div>
                                <button 
                                    type="button"
                                    className="text-muted-foreground hover:text-foreground transition-colors p-2 rounded-full hover:bg-accent"
                                    aria-label="Voice input"
                                >
                                    <Mic className="h-4 w-4" />
                                </button>
                                <button 
                                    type="submit" 
                                    disabled={!question.trim()}
                                    className={cn(
                                        "p-2 rounded-full transition-colors",
                                        question.trim()
                                            ? "bg-primary text-primary-foreground hover:bg-primary/90"
                                            : "bg-muted text-muted-foreground cursor-not-allowed"
                                    )}
                                    aria-label="Submit question"
                                >
                                    <Send className="h-4 w-4" />
                                </button>
                            </form>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
        </>
    )
}

