import { create } from 'zustand'
import { aiApi, type AIHistoryItem } from '@/lib/api/ai'

interface AIHistoryState {
    isOpen: boolean
    setIsOpen: (isOpen: boolean) => void
    toggle: () => void
    
    // History data
    historyItems: AIHistoryItem[]
    isLoading: boolean
    error: string | null
    
    // Actions
    fetchHistory: (params?: {
        filter?: 'today' | 'week' | 'pinned';
        search?: string;
        category?: string;
        skip?: number;
        limit?: number;
    }) => Promise<void>
    getHistoryById: (historyId: string) => Promise<AIHistoryItem>
    deleteHistory: (historyId: string) => Promise<void>
    pinHistory: (historyId: string) => Promise<void>
    unpinHistory: (historyId: string) => Promise<void>
    exportHistory: () => Promise<void>
}

export const useAIHistoryStore = create<AIHistoryState>((set, get) => ({
    isOpen: false,
    setIsOpen: (isOpen) => set({ isOpen }),
    toggle: () => set((state) => ({ isOpen: !state.isOpen })),
    
    historyItems: [],
    isLoading: false,
    error: null,
    
    fetchHistory: async (params) => {
        set({ isLoading: true, error: null })
        try {
            const items = await aiApi.getHistory(params)
            set({ historyItems: items, isLoading: false })
        } catch (error) {
            console.error('Error fetching AI history:', error)
            set({
                error: error instanceof Error ? error.message : 'Failed to fetch history',
                isLoading: false
            })
        }
    },
    
    getHistoryById: async (historyId) => {
        set({ isLoading: true, error: null })
        try {
            const item = await aiApi.getHistoryById(historyId)
            set({ isLoading: false })
            return item
        } catch (error) {
            console.error('Error fetching history item:', error)
            set({
                error: error instanceof Error ? error.message : 'Failed to fetch history item',
                isLoading: false
            })
            throw error
        }
    },
    
    deleteHistory: async (historyId) => {
        set({ isLoading: true, error: null })
        try {
            await aiApi.deleteHistory(historyId)
            set((state) => ({
                historyItems: state.historyItems.filter(item => item.id !== historyId),
                isLoading: false
            }))
        } catch (error) {
            console.error('Error deleting history:', error)
            set({
                error: error instanceof Error ? error.message : 'Failed to delete history',
                isLoading: false
            })
            throw error
        }
    },
    
    pinHistory: async (historyId) => {
        set({ isLoading: true, error: null })
        try {
            const updated = await aiApi.pinHistory(historyId)
            set((state) => ({
                historyItems: state.historyItems.map(item =>
                    item.id === historyId ? updated : item
                ),
                isLoading: false
            }))
        } catch (error) {
            console.error('Error pinning history:', error)
            set({
                error: error instanceof Error ? error.message : 'Failed to pin history',
                isLoading: false
            })
            throw error
        }
    },
    
    unpinHistory: async (historyId) => {
        set({ isLoading: true, error: null })
        try {
            const updated = await aiApi.unpinHistory(historyId)
            set((state) => ({
                historyItems: state.historyItems.map(item =>
                    item.id === historyId ? updated : item
                ),
                isLoading: false
            }))
        } catch (error) {
            console.error('Error unpinning history:', error)
            set({
                error: error instanceof Error ? error.message : 'Failed to unpin history',
                isLoading: false
            })
            throw error
        }
    },
    
    exportHistory: async () => {
        set({ isLoading: true, error: null })
        try {
            const blob = await aiApi.exportHistory()
            const url = window.URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = 'ai_history.csv'
            document.body.appendChild(a)
            a.click()
            window.URL.revokeObjectURL(url)
            document.body.removeChild(a)
            set({ isLoading: false })
        } catch (error) {
            console.error('Error exporting history:', error)
            set({
                error: error instanceof Error ? error.message : 'Failed to export history',
                isLoading: false
            })
            throw error
        }
    },
}))

