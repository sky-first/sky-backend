import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { dashboardsApi } from '@/lib/api/dashboards'
import { widgetsApi, type Widget as ApiWidget, type WidgetCreate } from '@/lib/api/widgets'
import { useDashboardStore } from './dashboard-store'
import { usePlanetStore } from './planet-store'

export type WidgetType = 'chart' | 'kpi' | 'table' | 'ai-box' | 'text'

export interface Widget {
    id: string
    type: WidgetType
    title: string
    position: { x: number; y: number }
    size: { width: number; height: number }
    data: any
    dashboard_id?: string // Optional, will be set when creating via API
}

export interface Connection {
    id: string
    from: string // widget id
    to: string // widget id
    fromAnchor: 'top' | 'right' | 'bottom' | 'left'
    toAnchor: 'top' | 'right' | 'bottom' | 'left'
}

interface WidgetState {
    widgets: Widget[]
    connections: Connection[]
    selectedWidgetId: string | null
    selectedWidgetIds: string[]
    connectingFrom: { widgetId: string; anchor: 'top' | 'right' | 'bottom' | 'left' } | null
    connectionDrag: { fromWidget: Widget; anchor: 'top' | 'right' | 'bottom' | 'left' } | null
    isLoading: boolean
    error: string | null
    pendingWidgets: Array<{ position: { x: number; y: number }; size: { width: number; height: number } }> // Widgets em criação
    
    // Actions
    setWidgets: (widgets: Widget[]) => void
    addWidget: (widget: Omit<Widget, 'id'>, dashboardId?: string) => Promise<string>
    updateWidget: (id: string, updates: Partial<Widget>, syncToBackend?: boolean) => Promise<void>
    removeWidget: (id: string) => Promise<void>
    removeWidgets: (ids: string[]) => Promise<void>
    selectWidget: (id: string | null) => void
    selectWidgets: (ids: string[]) => void
    clearSelection: () => void
    startConnection: (widgetId: string, anchor: 'top' | 'right' | 'bottom' | 'left') => void
    startConnectionDrag: (widget: Widget, anchor: 'top' | 'right' | 'bottom' | 'left') => void
    cancelConnection: () => void
    completeConnection: (toWidgetId: string, toAnchor: 'top' | 'right' | 'bottom' | 'left') => void
    removeConnection: (connectionId: string) => void
    addPendingWidget: (position: { x: number; y: number }, size: { width: number; height: number }) => void
    removePendingWidget: (position: { x: number; y: number }, size: { width: number; height: number }) => void
    clearPendingWidgets: () => void
    
    // API methods
    duplicateWidget: (widgetId: string) => Promise<Widget>
    refreshWidgetData: (widgetId: string) => Promise<void>
    getWidgetData: (widgetId: string) => Promise<any>
}

// Helper to convert API widget to store widget
const apiToStoreWidget = (apiWidget: ApiWidget): Widget => ({
    id: apiWidget.id,
    type: apiWidget.type,
    title: apiWidget.title,
    position: apiWidget.position,
    size: apiWidget.size,
    data: apiWidget.data || {},
    dashboard_id: apiWidget.dashboard_id,
})

// Helper to convert store widget to API widget create
const storeToApiWidgetCreate = (storeWidget: Omit<Widget, 'id'>, dashboardId: string): WidgetCreate => ({
    dashboard_id: dashboardId,
    type: storeWidget.type,
    title: storeWidget.title,
    position: storeWidget.position,
    size: storeWidget.size,
    data: storeWidget.data,
    config: undefined, // Can be added later if needed
})

// Debounce helper for update operations
let updateTimeout: NodeJS.Timeout | null = null
const DEBOUNCE_DELAY = 500 // 500ms debounce for updates

export const useWidgetStore = create<WidgetState>()(
    persist(
        (set, get) => ({
            widgets: [],
            connections: [],
            selectedWidgetId: null,
            selectedWidgetIds: [],
            connectingFrom: null,
            connectionDrag: null,
            isLoading: false,
            error: null,
            pendingWidgets: [],

            setWidgets: (widgets) => set({ widgets }),

            addWidget: async (widget, dashboardId) => {
                const currentDashboard = useDashboardStore.getState().currentDashboard
                const targetDashboardId = dashboardId || currentDashboard?.id
                
                if (!targetDashboardId) {
                    // Try to get current planet and create a dashboard
                    const { currentPlanet } = usePlanetStore.getState()
                    if (currentPlanet) {
                        try {
                            const { createDashboard } = useDashboardStore.getState()
                            const newDashboard = await createDashboard({
                                name: 'My Dashboard',
                                planet_id: currentPlanet.id,
                            })
                            // Use the newly created dashboard
                            const finalDashboardId = newDashboard.id
                            const apiData = storeToApiWidgetCreate(widget, finalDashboardId)
                            const apiWidget = await dashboardsApi.createWidget(finalDashboardId, apiData)
                            const storeWidget = apiToStoreWidget(apiWidget)
                            
                            // Use functional update to prevent race conditions
                            set((state) => {
                                // Check if widget already exists (prevent duplicates)
                                if (state.widgets.some(w => w.id === storeWidget.id)) {
                                    console.warn(`[WidgetStore] Widget ${storeWidget.id} already exists, skipping duplicate`)
                                    return { ...state, isLoading: false }
                                }
                                
                                const newWidgets = [...state.widgets, storeWidget]
                                console.log(`[WidgetStore] ✅ Widget ${storeWidget.id} added. Total widgets: ${newWidgets.length}`)
                                
                                return {
                                    widgets: newWidgets,
                                    isLoading: false,
                                }
                            })
                            
                            return storeWidget.id
                        } catch (error) {
                            console.error('Error creating dashboard and widget:', error)
                            throw new Error('Não foi possível criar um dashboard. Por favor, tente novamente.')
                        }
                    } else {
                        throw new Error('Por favor, selecione ou crie um Planet primeiro antes de criar widgets.')
                    }
                }

                set({ isLoading: true, error: null })
                try {
                    const apiData = storeToApiWidgetCreate(widget, targetDashboardId)
                    const apiWidget = await dashboardsApi.createWidget(targetDashboardId, apiData)
                    const storeWidget = apiToStoreWidget(apiWidget)
                    
                    // Use functional update to prevent race conditions
                    set((state) => {
                        // Check if widget already exists (prevent duplicates)
                        if (state.widgets.some(w => w.id === storeWidget.id)) {
                            console.warn(`[WidgetStore] Widget ${storeWidget.id} already exists, skipping duplicate`)
                            return { ...state, isLoading: false }
                        }
                        
                        const newWidgets = [...state.widgets, storeWidget]
                        console.log(`[WidgetStore] ✅ Widget ${storeWidget.id} added. Total widgets: ${newWidgets.length}`)
                        
                        return {
                            widgets: newWidgets,
                            isLoading: false,
                        }
                    })
                    
                    return storeWidget.id
                } catch (error) {
                    console.error('Error creating widget:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to create widget',
                        isLoading: false 
                    })
                    throw error
                }
            },

            updateWidget: async (id, updates, syncToBackend = true) => {
                // Update local state immediately for responsive UI
                set((state) => ({
                    widgets: state.widgets.map((w) => w.id === id ? { ...w, ...updates } : w)
                }))

                // Sync to backend with debouncing (unless explicitly requested immediate sync)
                if (syncToBackend) {
                    if (updateTimeout) {
                        clearTimeout(updateTimeout)
                    }
                    
                    updateTimeout = setTimeout(async () => {
                        try {
                            const widget = get().widgets.find(w => w.id === id)
                            if (!widget) return

                            // Convert store updates to API format
                            const apiUpdates: any = {}
                            if (updates.title !== undefined) apiUpdates.title = updates.title
                            if (updates.position !== undefined) apiUpdates.position = updates.position
                            if (updates.size !== undefined) apiUpdates.size = updates.size
                            if (updates.data !== undefined) apiUpdates.data = updates.data
                            // config, connection_id, query_id can be added if needed

                            await widgetsApi.updateWidget(id, apiUpdates)
                        } catch (error) {
                            console.error('Error updating widget:', error)
                            set({ 
                                error: error instanceof Error ? error.message : 'Failed to update widget'
                            })
                        }
                    }, syncToBackend ? DEBOUNCE_DELAY : 0)
                }
            },

            removeWidget: async (id) => {
                // Check if widget exists in local state
                const widgetExists = get().widgets.some(w => w.id === id)
                if (!widgetExists) {
                    // Widget doesn't exist in local state, nothing to do
                    return
                }

                // Optimistically remove from local state immediately for better UX
                set((state) => ({
                    widgets: state.widgets.filter((w) => w.id !== id),
                    selectedWidgetId: state.selectedWidgetId === id ? null : state.selectedWidgetId,
                    selectedWidgetIds: state.selectedWidgetIds.filter((wid) => wid !== id),
                }))

                // Try to delete from backend (fire and forget - don't block UI)
                try {
                    await widgetsApi.deleteWidget(id)
                } catch (error: any) {
                    // If widget not found (404), it's already deleted or never existed - that's fine
                    // Don't log as error, just silently handle it
                    if (error?.response?.status === 404) {
                        // Widget already deleted or doesn't exist - this is expected, no action needed
                        if (process.env.NODE_ENV === 'development') {
                            console.log(`[WidgetStore] Widget ${id} not found in backend (already deleted or never existed)`)
                        }
                    } else {
                        // Other errors - log but don't block UI since we already removed from local state
                        console.warn(`[WidgetStore] Failed to delete widget ${id} from backend:`, error instanceof Error ? error.message : 'Unknown error')
                        // Optionally, you could re-add the widget to local state here if you want to retry
                    }
                }
            },

            removeWidgets: async (ids) => {
                // Filter to only existing widgets
                const existingIds = ids.filter(id => get().widgets.some(w => w.id === id))
                if (existingIds.length === 0) {
                    // No widgets to delete
                    return
                }

                // Optimistically remove from local state first
                set((state) => ({
                    widgets: state.widgets.filter((w) => !existingIds.includes(w.id)),
                    selectedWidgetId: state.selectedWidgetId && existingIds.includes(state.selectedWidgetId) ? null : state.selectedWidgetId,
                    selectedWidgetIds: state.selectedWidgetIds.filter((wid) => !existingIds.includes(wid)),
                }))

                // Try to delete from backend in parallel (fire and forget)
                Promise.all(
                    existingIds.map(async (id) => {
                        try {
                            await widgetsApi.deleteWidget(id)
                        } catch (error: any) {
                            // 404 is expected if widget was already deleted - don't log as error
                            if (error?.response?.status !== 404) {
                                console.warn(`[WidgetStore] Failed to delete widget ${id}:`, error instanceof Error ? error.message : 'Unknown error')
                            }
                        }
                    })
                ).catch(() => {
                    // Ignore errors - widgets already removed from local state
                })
            },

            selectWidget: (id) => set({ selectedWidgetId: id, selectedWidgetIds: id ? [id] : [] }),
            selectWidgets: (ids) => set({ selectedWidgetIds: ids, selectedWidgetId: ids.length === 1 ? ids[0] : null }),
            clearSelection: () => set({ selectedWidgetId: null, selectedWidgetIds: [] }),
            
            startConnection: (widgetId, anchor) => set({ connectingFrom: { widgetId, anchor } }),
            startConnectionDrag: (widget, anchor) => set({ connectionDrag: { fromWidget: widget, anchor } }),
            cancelConnection: () => set({ connectingFrom: null, connectionDrag: null }),
            
            completeConnection: (toWidgetId, toAnchor) => set((state) => {
                if (!state.connectionDrag) return state
                const connection: Connection = {
                    id: Math.random().toString(36).substr(2, 9),
                    from: state.connectionDrag.fromWidget.id,
                    to: toWidgetId,
                    fromAnchor: state.connectionDrag.anchor,
                    toAnchor
                }
                return {
                    connections: [...state.connections, connection],
                    connectionDrag: null,
                    connectingFrom: null
                }
            }),
            
            removeConnection: (connectionId) => set((state) => ({
                connections: state.connections.filter((c) => c.id !== connectionId)
            })),
            
            addPendingWidget: (position, size) => set((state) => ({
                pendingWidgets: [...state.pendingWidgets, { position, size }]
            })),
            
            removePendingWidget: (position, size) => set((state) => ({
                pendingWidgets: state.pendingWidgets.filter(
                    (pw) => !(pw.position.x === position.x && pw.position.y === position.y && 
                              pw.size.width === size.width && pw.size.height === size.height)
                )
            })),
            
            clearPendingWidgets: () => set({ pendingWidgets: [] }),

            // API methods
            duplicateWidget: async (widgetId) => {
                set({ isLoading: true, error: null })
                try {
                    const apiWidget = await widgetsApi.duplicateWidget(widgetId)
                    const storeWidget = apiToStoreWidget(apiWidget)
                    set((state) => ({
                        widgets: [...state.widgets, storeWidget],
                        isLoading: false,
                    }))
                    return storeWidget
                } catch (error) {
                    console.error('Error duplicating widget:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to duplicate widget',
                        isLoading: false 
                    })
                    throw error
                }
            },

            refreshWidgetData: async (widgetId) => {
                set({ isLoading: true, error: null })
                try {
                    const data = await widgetsApi.refreshWidgetData(widgetId)
                    set((state) => ({
                        widgets: state.widgets.map((w) => 
                            w.id === widgetId ? { ...w, data: data.data } : w
                        ),
                        isLoading: false,
                    }))
                } catch (error) {
                    console.error('Error refreshing widget data:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to refresh widget data',
                        isLoading: false 
                    })
                    throw error
                }
            },

            getWidgetData: async (widgetId) => {
                try {
                    const data = await widgetsApi.getWidgetData(widgetId)
                    return data.data
                } catch (error) {
                    console.error('Error getting widget data:', error)
                    throw error
                }
            },
        }),
        {
            name: 'widget-storage',
            partialize: (state) => ({
                // Only persist UI state, not widget data (loaded from API)
                selectedWidgetId: state.selectedWidgetId,
                selectedWidgetIds: state.selectedWidgetIds,
            }),
        }
    )
)
