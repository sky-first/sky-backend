"use client"

import { useState } from "react"
import { useWidgetStore } from "@/store/widget-store"
import { useCanvasStore } from "@/store/canvas-store"
import { usePipelineStore } from "@/store/pipeline-store"
import { Send, Mic } from "lucide-react"

export function AISearchBar() {
    const [question, setQuestion] = useState("")
    const { addWidget } = useWidgetStore()
    const { getViewportCenter, snapPosition } = useCanvasStore()
    const { openForWidget } = usePipelineStore()

    const handleSubmitQuestion = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!question.trim()) return

        // Obter posição do centro do viewport
        const viewportCenter = getViewportCenter()
        // Aplicar snap se estiver habilitado
        const finalPosition = snapPosition(viewportCenter.x, viewportCenter.y)
        
        try {
            // Create KPI widget instead of AI Insights
            const widgetId = await addWidget({
                type: 'kpi',
                title: 'Analysis Result',
                position: finalPosition,
                size: { width: 300, height: 150 },
                data: { 
                    value: '0',
                    change: '0%'
                }
            })

            // Open pipeline overlay after widget is created
            setTimeout(() => {
                openForWidget({
                    widgetId: widgetId || '',
                    question: question,
                    answer: ''
                })
            }, 100)

            setQuestion("")
        } catch (error) {
            console.error('Error creating widget:', error)
        }
    }

    return (
        <div className="absolute bottom-16 left-1/2 transform -translate-x-1/2 z-10 pointer-events-auto" data-tour="ai-search">
            <form
                onSubmit={handleSubmitQuestion}
                className="rounded-full px-6 py-3 flex items-center gap-3 min-w-[500px] max-w-[600px] border-2 border-border bg-background/95 backdrop-blur-xl shadow-lg"
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
                    className="flex-1 bg-transparent text-foreground placeholder:text-muted-foreground outline-none text-sm font-medium"
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
        </div>
    )
}

