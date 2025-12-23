"use client"

import { useState, useRef, useEffect } from "react"
import { Widget } from "@/store/widget-store"
import { cn } from "@/lib/utils"
import { useTheme } from "next-themes"

interface TextWidgetProps {
    widget: Widget
    isSelected: boolean
    onUpdate: (content: string) => void
    onSelect: () => void
    onResize?: (height: number, width?: number) => void
}

export function TextWidget({ widget, isSelected, onUpdate, onSelect, onResize }: TextWidgetProps) {
    const [isEditing, setIsEditing] = useState(false)
    const [content, setContent] = useState(widget.data?.content || "")
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const { theme, resolvedTheme } = useTheme()

    const textData = widget.data || {}
    const fontFamily = textData.fontFamily || 'Noto Sans'
    const fontSize = textData.fontSize || 16
    const fontWeight = textData.fontWeight || 'normal'
    const textAlign = textData.textAlign || 'left'
    const textColor = textData.textColor || (resolvedTheme === 'dark' ? '#ffffff' : '#000000')
    const backgroundColor = textData.backgroundColor || 'transparent'
    const isLocked = textData.isLocked || false

    useEffect(() => {
        if (isEditing && textareaRef.current) {
            textareaRef.current.focus()
            // Move cursor to end
            const length = textareaRef.current.value.length
            textareaRef.current.setSelectionRange(length, length)
            // Initial resize
            requestAnimationFrame(() => {
                updateTextareaSize()
            })
        }
    }, [isEditing])

    useEffect(() => {
        if (widget.data?.content !== undefined && widget.data.content !== content) {
            setContent(widget.data.content || "")
        }
    }, [widget.data?.content])

    // Update widget size when content or font size changes
    useEffect(() => {
        if (isEditing && textareaRef.current) {
            requestAnimationFrame(() => {
                updateTextareaSize()
            })
        }
    }, [content, fontSize, fontFamily, fontWeight, isEditing])

    const handleBlur = () => {
        setIsEditing(false)
        onUpdate(content)
    }

    const handleDoubleClick = () => {
        // Don't allow editing if locked
        if (isLocked) return
        
        onSelect()
        setIsEditing(true)
    }

    const handleClick = (e: React.MouseEvent) => {
        // Don't allow editing if locked
        if (isLocked) return
        
        // Single click = just select, don't edit
        onSelect()
        // Don't set editing on single click
    }

    const updateTextareaSize = () => {
        if (textareaRef.current && onResize) {
            // Reset height to auto to get the correct scrollHeight
            textareaRef.current.style.height = 'auto'
            
            // Get scrollHeight which includes all content
            // Get scrollHeight and subtract extra space
            const textHeight = Math.max(textareaRef.current.scrollHeight - 4, 30) // Remove extra padding, min 30px
            
            // Calculate width based on content and font size
            // Use a canvas to measure text width more accurately
            const canvas = document.createElement('canvas')
            const context = canvas.getContext('2d')
            if (context) {
                context.font = `${fontWeight} ${fontSize}px ${fontFamily}`
                
                // Split content by lines and find the longest line
                const lines = (content || '').split('\n')
                let maxWidth = 0
                
                lines.forEach((line: string) => {
                    const metrics = context.measureText(line || ' ')
                    const lineWidth = metrics.width
                    maxWidth = Math.max(maxWidth, lineWidth)
                })
                
                // Add padding (12px left + 12px right = 24px)
                const textWidth = Math.min(Math.max(maxWidth + 24, 100), 800) // Min 100px, max 800px
                
                // Set the textarea dimensions to match content
                textareaRef.current.style.height = `${textHeight}px`
                textareaRef.current.style.width = `${textWidth}px`
                
                // Update widget size
                onResize(textHeight, textWidth)
            } else {
                // Fallback: just update height if canvas is not available
                textareaRef.current.style.height = `${textHeight}px`
                onResize(textHeight)
            }
        }
    }

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Escape') {
            setIsEditing(false)
            onUpdate(content)
        }
        // Allow Enter to create new line - will trigger resize
        if (e.key === 'Enter' && !e.shiftKey) {
            // Let the default behavior happen, then resize
            requestAnimationFrame(() => {
                updateTextareaSize()
            })
        }
    }

    const textStyle: React.CSSProperties = {
        fontFamily,
        fontSize: `${fontSize}px`,
        fontWeight,
        textAlign: textAlign as 'left' | 'center' | 'right',
        color: textColor,
        width: isEditing ? 'auto' : 'fit-content',
        minWidth: isEditing ? '100px' : 'auto',
        minHeight: 'auto',
        padding: '8px 12px',
        margin: 0,
        outline: 'none',
        border: 'none',
        background: 'transparent',
        resize: 'none',
        overflow: 'hidden',
        wordWrap: 'break-word',
        whiteSpace: 'pre-wrap',
        lineHeight: '1.4',
        letterSpacing: '0.01em',
        boxSizing: 'border-box',
        WebkitFontSmoothing: 'antialiased',
        MozOsxFontSmoothing: 'grayscale',
        textRendering: 'optimizeLegibility',
        fontFeatureSettings: '"liga" 1, "kern" 1',
        WebkitTextSizeAdjust: '100%',
    }

    return (
        <div 
            data-text-widget
            className={cn(
                "w-full h-full flex items-start",
                "rounded-lg border border-transparent",
                "hover:border-border/40",
                isSelected && "ring-0"
            )}
            onDoubleClick={handleDoubleClick}
            onClick={(e) => {
                // Only handle click if not editing
                if (!isEditing) {
                    handleClick(e)
                }
            }}
            onMouseDown={(e) => {
                // Don't interfere with drag - let Rnd handle it
                // Only prevent canvas pan for textarea
                const target = e.target as HTMLElement
                const isTextarea = target.tagName === 'TEXTAREA' || target.closest('textarea')
                
                // Only stop propagation for textarea to prevent canvas pan
                // For everything else, let the event bubble so Rnd can handle drag
                if (isTextarea) {
                    e.stopPropagation()
                }
                // Don't prevent default - let Rnd handle drag detection
            }}
            style={{
                userSelect: isEditing ? 'text' : 'none',
                WebkitUserSelect: isEditing ? 'text' : 'none',
            }}
        >
            {isEditing ? (
                <textarea
                    ref={textareaRef}
                    value={content}
                    onChange={(e) => {
                        setContent(e.target.value)
                        // Auto-resize textarea and widget immediately
                        requestAnimationFrame(() => {
                            updateTextareaSize()
                        })
                    }}
                    onFocus={() => {
                        // Ensure widget is selected when textarea gets focus
                        if (!isSelected) {
                            onSelect()
                        }
                    }}
                    onBlur={handleBlur}
                    onKeyDown={handleKeyDown}
                    onMouseDown={(e) => e.stopPropagation()}
                    style={textStyle}
                    className={cn(
                        "resize-none text-widget-editable",
                        "rounded-md",
                        "outline-none focus-visible:ring-2 focus-visible:ring-blue-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                    )}
                    placeholder=""
                />
            ) : (
                <div
                    style={textStyle}
                    className={cn(
                        "cursor-grab active:cursor-grabbing text-widget-editable",
                        content === "" && "text-muted-foreground/50"
                    )}
                    onDoubleClick={handleDoubleClick}
                >
                    {content || "Double click to edit"}
                </div>
            )}
        </div>
    )
}

