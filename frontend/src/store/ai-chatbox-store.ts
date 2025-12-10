import { create } from 'zustand'

interface AIChatboxState {
    shouldOpen: boolean
    widgetId: string | null
    initialQuestion: string | null
    initialAnswer: string | null
    openForWidget: (widgetId: string, question: string, answer: string) => void
    close: () => void
}

export const useAIChatboxStore = create<AIChatboxState>((set) => ({
    shouldOpen: false,
    widgetId: null,
    initialQuestion: null,
    initialAnswer: null,
    openForWidget: (widgetId: string, question: string, answer: string) => {
        set({
            shouldOpen: true,
            widgetId,
            initialQuestion: question,
            initialAnswer: answer,
        })
    },
    close: () => {
        set({
            shouldOpen: false,
            widgetId: null,
            initialQuestion: null,
            initialAnswer: null,
        })
    },
}))
