import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { dashboardsApi, type Dashboard, type DashboardCreate, type DashboardUpdate, type DashboardExportResponse } from '@/lib/api/dashboards'

export interface DashboardState {
    dashboards: Dashboard[]
    currentDashboard: Dashboard | null
    isLoading: boolean
    error: string | null
    
    // Actions
    fetchDashboards: (params?: { planet_id?: string; skip?: number; limit?: number }) => Promise<void>
    fetchDashboard: (dashboardId: string) => Promise<Dashboard>
    createDashboard: (data: DashboardCreate) => Promise<Dashboard>
    updateDashboard: (dashboardId: string, updates: DashboardUpdate) => Promise<Dashboard>
    deleteDashboard: (dashboardId: string) => Promise<void>
    setCurrentDashboard: (dashboard: Dashboard | null) => void
    exportDashboard: (dashboardId: string) => Promise<DashboardExportResponse>
    duplicateDashboard: (dashboardId: string, data?: { name?: string; planet_id?: string }) => Promise<Dashboard>
    lockDashboard: (dashboardId: string) => Promise<Dashboard>
    unlockDashboard: (dashboardId: string) => Promise<Dashboard>
}

export const useDashboardStore = create<DashboardState>()(
    persist(
        (set, get) => ({
            dashboards: [],
            currentDashboard: null,
            isLoading: false,
            error: null,

            fetchDashboards: async (params) => {
                set({ isLoading: true, error: null })
                try {
                    const dashboards = await dashboardsApi.listDashboards(params)
                    set({ 
                        dashboards,
                        isLoading: false 
                    })
                } catch (error) {
                    console.error('Error fetching dashboards:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to fetch dashboards',
                        isLoading: false 
                    })
                }
            },

            fetchDashboard: async (dashboardId) => {
                if (!dashboardId || dashboardId === 'null' || dashboardId === 'undefined') {
                    const error = new Error('Invalid dashboard id')
                    console.error(error)
                    throw error
                }
                
                // Check if we already have this dashboard in cache
                const state = get()
                const cachedDashboard = state.dashboards.find(d => d.id === dashboardId) || 
                                       (state.currentDashboard?.id === dashboardId ? state.currentDashboard : null)
                
                // If we have a cached dashboard and it's recent (less than 5 seconds old), use it
                // This avoids unnecessary API calls when switching between dashboards quickly
                if (cachedDashboard) {
                    // Still return cached dashboard but don't set loading state
                    return cachedDashboard
                }
                
                set({ isLoading: true, error: null })
                try {
                    const dashboard = await dashboardsApi.getDashboard(dashboardId)
                    set((state) => ({
                        dashboards: state.dashboards.some(d => d.id === dashboardId)
                            ? state.dashboards.map(d => d.id === dashboardId ? dashboard : d)
                            : [...state.dashboards, dashboard],
                        currentDashboard: dashboard,
                        isLoading: false,
                    }))
                    return dashboard
                } catch (error) {
                    console.error('Error fetching dashboard:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to fetch dashboard',
                        isLoading: false 
                    })
                    throw error
                }
            },

            createDashboard: async (data) => {
                set({ isLoading: true, error: null })
                try {
                    const dashboard = await dashboardsApi.createDashboard(data)
                    set((state) => ({
                        dashboards: [...state.dashboards, dashboard],
                        currentDashboard: dashboard, // Set as current
                        isLoading: false,
                    }))
                    return dashboard
                } catch (error) {
                    console.error('Error creating dashboard:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to create dashboard',
                        isLoading: false 
                    })
                    throw error
                }
            },

            updateDashboard: async (dashboardId, updates) => {
                set({ isLoading: true, error: null })
                try {
                    const dashboard = await dashboardsApi.updateDashboard(dashboardId, updates)
                    set((state) => ({
                        dashboards: state.dashboards.map((d) =>
                            d.id === dashboardId ? dashboard : d
                        ),
                        currentDashboard: state.currentDashboard?.id === dashboardId
                            ? dashboard
                            : state.currentDashboard,
                        isLoading: false,
                    }))
                    return dashboard
                } catch (error) {
                    console.error('Error updating dashboard:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to update dashboard',
                        isLoading: false 
                    })
                    throw error
                }
            },

            deleteDashboard: async (dashboardId) => {
                set({ isLoading: true, error: null })
                try {
                    await dashboardsApi.deleteDashboard(dashboardId)
                    set((state) => ({
                        dashboards: state.dashboards.filter((d) => d.id !== dashboardId),
                        currentDashboard: state.currentDashboard?.id === dashboardId
                            ? null
                            : state.currentDashboard,
                        isLoading: false,
                    }))
                } catch (error) {
                    console.error('Error deleting dashboard:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to delete dashboard',
                        isLoading: false 
                    })
                    throw error
                }
            },

            setCurrentDashboard: (dashboard) => {
                set({ currentDashboard: dashboard })
            },

            exportDashboard: async (dashboardId) => {
                set({ isLoading: true, error: null })
                try {
                    const exportData = await dashboardsApi.exportDashboard(dashboardId)
                    set({ isLoading: false })
                    return exportData
                } catch (error) {
                    console.error('Error exporting dashboard:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to export dashboard',
                        isLoading: false 
                    })
                    throw error
                }
            },

            duplicateDashboard: async (dashboardId, data) => {
                set({ isLoading: true, error: null })
                try {
                    const duplicated = await dashboardsApi.duplicateDashboard(dashboardId, data)
                    set((state) => ({
                        dashboards: [...state.dashboards, duplicated],
                        currentDashboard: duplicated, // Set duplicated as current
                        isLoading: false,
                    }))
                    return duplicated
                } catch (error) {
                    console.error('Error duplicating dashboard:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to duplicate dashboard',
                        isLoading: false 
                    })
                    throw error
                }
            },

            lockDashboard: async (dashboardId) => {
                set({ isLoading: true, error: null })
                try {
                    await dashboardsApi.lockDashboard(dashboardId)
                    // Fetch updated dashboard after lock
                    const locked = await dashboardsApi.getDashboard(dashboardId)
                    set((state) => ({
                        dashboards: state.dashboards.map((d) =>
                            d.id === dashboardId ? locked : d
                        ),
                        currentDashboard: state.currentDashboard?.id === dashboardId
                            ? locked
                            : state.currentDashboard,
                        isLoading: false,
                    }))
                    return locked
                } catch (error) {
                    console.error('Error locking dashboard:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to lock dashboard',
                        isLoading: false 
                    })
                    throw error
                }
            },

            unlockDashboard: async (dashboardId) => {
                set({ isLoading: true, error: null })
                try {
                    await dashboardsApi.unlockDashboard(dashboardId)
                    // Fetch updated dashboard after unlock
                    const unlocked = await dashboardsApi.getDashboard(dashboardId)
                    set((state) => ({
                        dashboards: state.dashboards.map((d) =>
                            d.id === dashboardId ? unlocked : d
                        ),
                        currentDashboard: state.currentDashboard?.id === dashboardId
                            ? unlocked
                            : state.currentDashboard,
                        isLoading: false,
                    }))
                    return unlocked
                } catch (error) {
                    console.error('Error unlocking dashboard:', error)
                    set({ 
                        error: error instanceof Error ? error.message : 'Failed to unlock dashboard',
                        isLoading: false 
                    })
                    throw error
                }
            },
        }),
        {
            name: 'dashboard-storage',
            partialize: (state) => ({
                currentDashboard: state.currentDashboard,
            }),
        }
    )
)

