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
    Link as LinkIcon, 
    Palette,
    Pen,
    CircleOff,
    MessageSquare,
    Lock,
    Sparkles,
    MoreVertical
} from "lucide-react"
import { useWidgetStore } from "@/store/widget-store"
import { useTheme } from "next-themes"
import { cn } from "@/lib/utils"
import { useEffect, useState } from "react"

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

export function TextToolbar() {
    const { selectedWidgetId, widgets, updateWidget } = useWidgetStore()
    const { theme, resolvedTheme } = useTheme()
    const [mounted, setMounted] = useState(false)
    
    const selectedWidget = widgets.find(w => w.id === selectedWidgetId)
    const isTextWidget = selectedWidget?.type === 'text'
    
    useEffect(() => {
        setMounted(true)
    }, [])

    if (!mounted || !isTextWidget || !selectedWidget) return null

    const currentTheme = resolvedTheme || theme || 'light'
    const isDark = currentTheme === 'dark'
    
    const textData = selectedWidget.data || {}
    const fontFamily = textData.fontFamily || 'Noto Sans'
    const fontSize = textData.fontSize || 16
    const fontWeight = textData.fontWeight || 'normal'
    const textAlign = textData.textAlign || 'left'
    const textColor = textData.textColor || (isDark ? '#ffffff' : '#000000')
    const isBold = fontWeight === 'bold' || fontWeight === '700'

    const toolbarStyle = {
        borderRadius: "0.5rem",
        padding: "0.5rem 0.75rem",
        border: isDark 
            ? "1px solid rgba(255, 255, 255, 0.1)" 
            : "1px solid rgba(0, 0, 0, 0.1)",
        background: isDark 
            ? "rgba(15, 23, 42, 0.95)" 
            : "rgba(255, 255, 255, 0.95)",
        backdropFilter: "blur(12px) saturate(180%)",
        WebkitBackdropFilter: "blur(12px) saturate(180%)",
        boxShadow: isDark 
            ? "0 4px 20px rgba(0, 0, 0, 0.3), 0 1px 4px rgba(0, 0, 0, 0.2)" 
            : "0 4px 20px rgba(0, 0, 0, 0.1), 0 1px 4px rgba(0, 0, 0, 0.05)",
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

    return (
        <div 
            className="fixed top-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-1.5 transition-all duration-200"
            style={toolbarStyle}
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

            {/* Link */}
            <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
            >
                <LinkIcon className="w-4 h-4" />
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

            {/* Pen/Highlight */}
            <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
            >
                <Pen className="w-4 h-4" />
            </Button>

            {/* Transparent/No Fill */}
            <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
            >
                <CircleOff className="w-4 h-4" />
            </Button>

            {/* Separator */}
            <div className={cn(
                "w-px h-6 mx-1",
                isDark ? "bg-white/20" : "bg-black/20"
            )} />

            {/* Comment */}
            <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
            >
                <MessageSquare className="w-4 h-4" />
            </Button>

            {/* Lock */}
            <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
            >
                <Lock className="w-4 h-4" />
            </Button>

            {/* AI/Sparkles */}
            <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-purple-500"
            >
                <Sparkles className="w-4 h-4" />
            </Button>

            {/* More Options */}
            <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
            >
                <MoreVertical className="w-4 h-4" />
            </Button>
        </div>
    )
}

