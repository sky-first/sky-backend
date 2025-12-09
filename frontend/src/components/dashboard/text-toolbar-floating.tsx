"use client"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { 
    Type, 
    Bold, 
    AlignLeft, 
    AlignCenter, 
    AlignRight, 
    Palette,
    Pen,
    CircleOff,
    MessageSquare,
    Lock,
    MoreVertical,
    Copy,
    Trash2,
    RotateCcw,
    Layers,
    X,
    ChevronDown
} from "lucide-react"
import { useWidgetStore } from "@/store/widget-store"
import { useCanvasStore } from "@/store/canvas-store"
import { useTheme } from "next-themes"
import { cn } from "@/lib/utils"
import { useEffect, useState, useRef, useCallback } from "react"
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

const FONT_FAMILIES = [
    "Noto Sans",
    "Inter",
    "Roboto",
    "Open Sans",
    "Lato",
    "Montserrat",
    "Poppins",
    "Playfair Display",
    "Merriweather",
    "Georgia",
    "Times New Roman",
    "Arial",
    "Helvetica",
    "Courier New",
    "Monaco"
]

export function TextToolbarFloating() {
    const { selectedWidgetId, widgets, updateWidget, addWidget, removeWidget } = useWidgetStore()
    const { scale, position: canvasPosition, getViewportCenter } = useCanvasStore()
    const { theme, resolvedTheme } = useTheme()
    const [mounted, setMounted] = useState(false)
    const [toolbarPosition, setToolbarPosition] = useState({ top: 0, left: 0 })
    const [isVisible, setIsVisible] = useState(true)
    const [isMinimized, setIsMinimized] = useState(false)
    const toolbarRef = useRef<HTMLDivElement>(null)
    const rafIdRef = useRef<number | null>(null)
    const [copiedStyle, setCopiedStyle] = useState<any>(null)
    
    const selectedWidget = widgets.find(w => w.id === selectedWidgetId)
    const isTextWidget = selectedWidget?.type === 'text'
    
    useEffect(() => {
        setMounted(true)
    }, [])

    // Optimized position update function
    const updatePosition = useCallback(() => {
        if (!isTextWidget || !selectedWidget || !toolbarRef.current) {
            if (rafIdRef.current) {
                cancelAnimationFrame(rafIdRef.current)
                rafIdRef.current = null
            }
            return
        }

        const widgetElement = document.querySelector(`[data-widget-id="${selectedWidget.id}"]`) as HTMLElement
        if (!widgetElement) {
            rafIdRef.current = requestAnimationFrame(updatePosition)
            return
        }

        const widgetRect = widgetElement.getBoundingClientRect()
        const toolbarHeight = toolbarRef.current.offsetHeight || 50
        const toolbarWidth = toolbarRef.current.offsetWidth || 600
        
        // Check visibility with generous margin
        const margin = 400
        const isVisibleInViewport = (
            widgetRect.right > -margin &&
            widgetRect.left < window.innerWidth + margin &&
            widgetRect.bottom > -margin &&
            widgetRect.top < window.innerHeight + margin
        )

        if (!isMinimized) {
            if (isVisibleInViewport) {
                // Widget is visible - show toolbar
                setIsVisible(true)
                
                // Calculate position
                const centerX = widgetRect.left + (widgetRect.width / 2)
                const topY = widgetRect.top - toolbarHeight - 12
                
                // Clamp to viewport
                const clampedX = Math.max(toolbarWidth / 2, Math.min(centerX, window.innerWidth - toolbarWidth / 2))
                const clampedY = Math.max(8, Math.min(topY, window.innerHeight - toolbarHeight - 8))
                
                // Update position immediately (no threshold to avoid delays)
                setToolbarPosition({ top: clampedY, left: clampedX })
            } else {
                // Widget is far - hide toolbar
                setIsVisible(false)
            }
        }

        // Continue loop
        rafIdRef.current = requestAnimationFrame(updatePosition)
    }, [isTextWidget, selectedWidget?.id, isMinimized])

    // Main effect for position tracking
    useEffect(() => {
        if (!isTextWidget || !selectedWidget) {
            if (rafIdRef.current) {
                cancelAnimationFrame(rafIdRef.current)
                rafIdRef.current = null
            }
            return
        }

        // Start animation loop
        rafIdRef.current = requestAnimationFrame(updatePosition)

        return () => {
            if (rafIdRef.current) {
                cancelAnimationFrame(rafIdRef.current)
                rafIdRef.current = null
            }
        }
    }, [isTextWidget, selectedWidget?.id, selectedWidget?.position?.x, selectedWidget?.position?.y, selectedWidget?.size?.width, selectedWidget?.size?.height, scale, canvasPosition.x, canvasPosition.y, isMinimized, updatePosition])

    // Reset minimized state and show toolbar when widget is selected
    useEffect(() => {
        if (isTextWidget && selectedWidget) {
            setIsMinimized(false)
            setIsVisible(true)
        } else {
            setIsVisible(false)
        }
    }, [selectedWidget?.id, isTextWidget, selectedWidget])

    // Don't render if not mounted, not a text widget, or no widget selected
    if (!mounted || !isTextWidget || !selectedWidget) return null

    const currentTheme = resolvedTheme || theme || 'light'
    const isDark = currentTheme === 'dark'
    
    const textData = selectedWidget.data || {}
    const fontFamily = textData.fontFamily || 'Noto Sans'
    const fontSize = textData.fontSize || 16
    const fontWeight = textData.fontWeight || 'normal'
    const textAlign = textData.textAlign || 'left'
    const textColor = textData.textColor || (isDark ? '#ffffff' : '#000000')
    const backgroundColor = textData.backgroundColor || 'transparent'
    const isBold = fontWeight === 'bold' || fontWeight === '700'
    const isLocked = textData.isLocked || false
    const hasBackground = backgroundColor !== 'transparent' && backgroundColor !== ''

    const toolbarStyle = {
        borderRadius: "0.75rem",
        padding: "0.5rem 0.75rem",
        border: isDark 
            ? "1px solid rgba(255, 255, 255, 0.12)" 
            : "1px solid rgba(0, 0, 0, 0.08)",
        background: isDark 
            ? "rgba(15, 23, 42, 0.98)" 
            : "rgba(255, 255, 255, 0.98)",
        backdropFilter: "blur(20px) saturate(200%)",
        WebkitBackdropFilter: "blur(20px) saturate(200%)",
        boxShadow: isDark 
            ? "0 8px 32px rgba(0, 0, 0, 0.4), 0 2px 8px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.1)" 
            : "0 8px 32px rgba(0, 0, 0, 0.12), 0 2px 8px rgba(0, 0, 0, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.9)",
        WebkitFontSmoothing: 'antialiased',
        MozOsxFontSmoothing: 'grayscale',
        textRendering: 'optimizeLegibility',
    }

    const updateTextData = (updates: any) => {
        updateWidget(selectedWidget.id, {
            data: { ...textData, ...updates }
        })
    }

    const handleFontSizeChange = (value: string) => {
        const size = parseInt(value) || 16
        if (size >= 8 && size <= 500) {
            updateTextData({ fontSize: size })
        }
    }

    const handleFontSizeIncrement = () => {
        const newSize = Math.min(fontSize + 1, 500)
        updateTextData({ fontSize: newSize })
    }

    const handleFontSizeDecrement = () => {
        const newSize = Math.max(fontSize - 1, 8)
        updateTextData({ fontSize: newSize })
    }

    const handleDuplicate = () => {
        if (!selectedWidget) return
        
        const viewportCenter = getViewportCenter()
        const offset = 20
        
        addWidget({
            type: 'text',
            title: `${selectedWidget.title} (cópia)`,
            position: {
                x: selectedWidget.position.x + offset,
                y: selectedWidget.position.y + offset
            },
            size: { ...selectedWidget.size },
            data: { ...selectedWidget.data }
        }).catch(console.error)
    }

    const handleCopyStyle = () => {
        if (!selectedWidget) return
        const styleToCopy = {
            fontFamily: textData.fontFamily,
            fontSize: textData.fontSize,
            fontWeight: textData.fontWeight,
            textAlign: textData.textAlign,
            textColor: textData.textColor,
            backgroundColor: textData.backgroundColor,
        }
        setCopiedStyle(styleToCopy)
    }

    const handlePasteStyle = () => {
        if (!copiedStyle || !selectedWidget) return
        updateTextData(copiedStyle)
    }

    const handleResetStyle = () => {
        const defaultStyle = {
            fontFamily: 'Noto Sans',
            fontSize: 16,
            fontWeight: 'normal',
            textAlign: 'left',
            textColor: isDark ? '#ffffff' : '#000000',
            backgroundColor: 'transparent',
        }
        updateTextData(defaultStyle)
    }

    const handleDelete = () => {
        if (!selectedWidget) return
        removeWidget(selectedWidget.id)
    }

    // Show restore button when minimized
    if (isMinimized) {
        const widgetElement = document.querySelector(`[data-widget-id="${selectedWidget.id}"]`)
        if (!widgetElement) return null
        
        const widgetRect = widgetElement.getBoundingClientRect()
        const restoreButtonTop = widgetRect.top - 40
        const restoreButtonLeft = widgetRect.left + (widgetRect.width / 2)
        
        return (
            <div 
                className="fixed z-50 pointer-events-auto"
                style={{
                    top: `${restoreButtonTop}px`,
                    left: `${restoreButtonLeft}px`,
                    transform: 'translateX(-50%)',
                }}
            >
                <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 bg-white/95 border border-gray-200/90 rounded-full shadow-[0_2px_8px_rgba(0,0,0,0.1)] backdrop-blur-md hover:bg-white"
                    onClick={() => setIsMinimized(false)}
                    title="Restaurar barra de ferramentas"
                >
                    <ChevronDown className="w-4 h-4 rotate-180" />
                </Button>
            </div>
        )
    }
    
    if (!isVisible) return null

    return (
        <div 
            ref={toolbarRef}
            data-text-toolbar
            className="fixed z-50 flex items-center gap-1.5 pointer-events-auto"
            style={{
                ...toolbarStyle,
                top: `${toolbarPosition.top}px`,
                left: `${toolbarPosition.left}px`,
                transform: 'translateX(-50%)',
                willChange: 'transform',
                WebkitFontSmoothing: 'antialiased',
                MozOsxFontSmoothing: 'grayscale',
                textRendering: 'optimizeLegibility',
            }}
        >
            {/* Text Tool Icon */}
            <div className="flex items-center justify-center h-8 w-8 px-2">
                <Type className="w-4 h-4" />
            </div>

            {/* Font Family Selector */}
            <Select value={fontFamily} onValueChange={(value) => updateTextData({ fontFamily: value })}>
                <SelectTrigger className="h-8 w-[140px] text-xs">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {FONT_FAMILIES.map((font) => (
                        <SelectItem key={font} value={font}>
                            {font}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>

            {/* Font Size Input */}
            <div className="flex items-center gap-0.5 border rounded-md h-8">
                <Input
                    type="number"
                    value={fontSize}
                    onChange={(e) => handleFontSizeChange(e.target.value)}
                    className="h-8 w-16 text-xs text-center border-0 focus-visible:ring-0"
                    min={8}
                    max={500}
                />
                <div className="flex flex-col border-l h-full">
                    <button
                        onClick={handleFontSizeIncrement}
                        className="h-1/2 w-5 flex items-center justify-center hover:bg-accent text-[10px] leading-none"
                    >
                        ▲
                    </button>
                    <button
                        onClick={handleFontSizeDecrement}
                        className="h-1/2 w-5 flex items-center justify-center hover:bg-accent text-[10px] leading-none border-t"
                    >
                        ▼
                    </button>
                </div>
            </div>

            {/* Bold */}
            <Button
                variant={isBold ? "default" : "ghost"}
                size="icon"
                className={cn("h-8 w-8", isBold && "bg-primary/20")}
                onClick={() => updateTextData({ fontWeight: isBold ? 'normal' : 'bold' })}
            >
                <Bold className="w-4 h-4" />
            </Button>

            {/* Align Left */}
            <Button
                variant={textAlign === 'left' ? "default" : "ghost"}
                size="icon"
                className={cn("h-8 w-8", textAlign === 'left' && "bg-primary/20")}
                onClick={() => updateTextData({ textAlign: 'left' })}
            >
                <AlignLeft className="w-4 h-4" />
            </Button>

            {/* Align Center */}
            <Button
                variant={textAlign === 'center' ? "default" : "ghost"}
                size="icon"
                className={cn("h-8 w-8", textAlign === 'center' && "bg-primary/20")}
                onClick={() => updateTextData({ textAlign: 'center' })}
            >
                <AlignCenter className="w-4 h-4" />
            </Button>

            {/* Align Right */}
            <Button
                variant={textAlign === 'right' ? "default" : "ghost"}
                size="icon"
                className={cn("h-8 w-8", textAlign === 'right' && "bg-primary/20")}
                onClick={() => updateTextData({ textAlign: 'right' })}
            >
                <AlignRight className="w-4 h-4" />
            </Button>

            {/* Text Color */}
            <div className="relative">
                <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                >
                    <Palette className="w-4 h-4" />
                </Button>
                <input
                    type="color"
                    value={textColor}
                    onChange={(e) => updateTextData({ textColor: e.target.value })}
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                />
            </div>

            {/* Pen/Highlight - Background Color */}
            <div className="relative">
                <Button
                    variant={hasBackground ? "default" : "ghost"}
                    size="icon"
                    className={cn("h-8 w-8", hasBackground && "bg-primary/20")}
                    title="Cor de fundo"
                >
                    <Pen className="w-4 h-4" />
                </Button>
                <input
                    type="color"
                    value={hasBackground ? backgroundColor : '#ffffff'}
                    onChange={(e) => updateTextData({ backgroundColor: e.target.value })}
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                />
            </div>

            {/* Transparent/No Fill - Remove Background */}
            <Button
                variant={!hasBackground ? "default" : "ghost"}
                size="icon"
                className={cn("h-8 w-8", !hasBackground && "bg-primary/20")}
                onClick={() => updateTextData({ backgroundColor: 'transparent' })}
                title="Remover cor de fundo"
            >
                <CircleOff className="w-4 h-4" />
            </Button>

            {/* Separator */}
            <div className={cn(
                "w-px h-6 mx-1",
                isDark ? "bg-white/20" : "bg-black/20"
            )} />

            {/* Comment - Placeholder for future feature */}
            <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                title="Comentários (em breve)"
                disabled
            >
                <MessageSquare className="w-4 h-4 opacity-50" />
            </Button>

            {/* Lock - Toggle lock/unlock editing */}
            <Button
                variant={isLocked ? "default" : "ghost"}
                size="icon"
                className={cn("h-8 w-8", isLocked && "bg-primary/20")}
                onClick={() => updateTextData({ isLocked: !isLocked })}
                title={isLocked ? "Desbloquear edição" : "Bloquear edição"}
            >
                <Lock className={cn("w-4 h-4", isLocked && "fill-current")} />
            </Button>

            {/* Minimize Button */}
            <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => setIsMinimized(true)}
                title="Minimizar barra de ferramentas"
            >
                <ChevronDown className="w-4 h-4" />
            </Button>

            {/* More Options - Dropdown Menu */}
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        title="Mais opções"
                    >
                        <MoreVertical className="w-4 h-4" />
                    </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                    <DropdownMenuItem onClick={handleDuplicate}>
                        <Layers className="w-4 h-4 mr-2" />
                        Duplicar
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={handleCopyStyle}>
                        <Copy className="w-4 h-4 mr-2" />
                        Copiar estilo
                    </DropdownMenuItem>
                    <DropdownMenuItem 
                        onClick={handlePasteStyle}
                        disabled={!copiedStyle}
                    >
                        <Copy className="w-4 h-4 mr-2" />
                        Colar estilo
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={handleResetStyle}>
                        <RotateCcw className="w-4 h-4 mr-2" />
                        Resetar formatação
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem 
                        onClick={() => updateTextData({ isLocked: !isLocked })}
                    >
                        <Lock className={cn("w-4 h-4 mr-2", isLocked && "fill-current")} />
                        {isLocked ? "Desbloquear" : "Bloquear"}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem 
                        onClick={handleDelete}
                        variant="destructive"
                    >
                        <Trash2 className="w-4 h-4 mr-2" />
                        Deletar
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}

