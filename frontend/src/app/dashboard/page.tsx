"use client"

import { useEffect, useState, Suspense, useCallback, useMemo } from "react"
import { useSearchParams, useRouter } from "next/navigation"
import { Canvas } from "@/components/dashboard/canvas"
import { WidgetContainer } from "@/components/dashboard/widget-container"
import { Toolbar } from "@/components/dashboard/toolbar"
import { useWidgetStore } from "@/store/widget-store"
import { useDashboardStore } from "@/store/dashboard-store"
import { usePlanetStore } from "@/store/planet-store"
import { useCanvasStore } from "@/store/canvas-store"
import { dashboardsApi } from "@/lib/api/dashboards"
import { Loader2 } from "lucide-react"

// Helper function to convert API widgets to store format (optimized with loop)
const convertApiWidgetsToStore = (apiWidgets: any[]): any[] => {
    if (!apiWidgets || apiWidgets.length === 0) return []
    const storeWidgets = new Array(apiWidgets.length)
    for (let i = 0; i < apiWidgets.length; i++) {
        const w = apiWidgets[i]
        storeWidgets[i] = {
            id: w.id,
            type: (w.type as 'chart' | 'kpi' | 'table' | 'ai-box' | 'text') || 'text',
            title: w.title || '',
            position: w.position || { x: 0, y: 0 },
            size: w.size || { width: 400, height: 300 },
            data: w.data || w.config || {},
        }
    }
    return storeWidgets
}

function DashboardContent() {
    const searchParams = useSearchParams()
    const router = useRouter()
    // Normalize dashboardId param so values like "null"/"undefined"/empty don't trigger invalid requests
    const rawDashboardId = searchParams.get('id')
    const dashboardId = useMemo(() => {
        const normalized = rawDashboardId?.trim()
        return normalized && normalized !== 'null' && normalized !== 'undefined' ? normalized : null
    }, [rawDashboardId])
    
    // Use Zustand selectors to avoid unnecessary re-renders
    const widgets = useWidgetStore(state => state.widgets)
    const setWidgets = useWidgetStore(state => state.setWidgets)
    const currentDashboard = useDashboardStore(state => state.currentDashboard)
    const fetchDashboard = useDashboardStore(state => state.fetchDashboard)
    const setCurrentDashboard = useDashboardStore(state => state.setCurrentDashboard)
    const updateDashboard = useDashboardStore(state => state.updateDashboard)
    const currentPlanet = usePlanetStore(state => state.currentPlanet)
    const loadSettings = useCanvasStore(state => state.loadSettings)
    
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    // If the URL contains an invalid dashboard id, clean it up to avoid repeated failing calls
    useEffect(() => {
        if (rawDashboardId && (!dashboardId || dashboardId === '')) {
            router.replace('/dashboard')
        }
    }, [rawDashboardId, dashboardId, router])

    // Memoize loadWidgets function (kept for backward compatibility but optimized to use parallel loading)
    const loadWidgets = useCallback(async (dashboardId: string, isMounted: boolean) => {
            try {
                if (!isMounted) return
                const apiWidgets = await dashboardsApi.getWidgets(dashboardId)
                if (!isMounted) return
                
                // Convert API widgets to store format (optimized)
                const storeWidgets = convertApiWidgetsToStore(apiWidgets)
                if (isMounted) {
                    setWidgets(storeWidgets)
                }
            } catch (err) {
                console.error('Error loading widgets:', err)
                // Don't set error here, just log it - widgets might be empty
                // Set empty widgets array to prevent UI issues
                if (isMounted) {
                    setWidgets([])
                }
            }
    }, [setWidgets])

    // Load dashboard and widgets
    useEffect(() => {
        let isMounted = true

        const loadDashboardForPlanet = async (planetId: string) => {
            try {
                if (!isMounted) return
                setIsLoading(true)
                setError(null)
                
                // Validate planetId
                if (!planetId || planetId === 'null' || planetId === 'undefined') {
                    throw new Error('Invalid planet ID')
                }
                
                if (process.env.NODE_ENV === 'development') {
                    console.log('[Dashboard] Loading dashboards for planet:', planetId)
                }
                let dashboards
                try {
                    dashboards = await dashboardsApi.listDashboards({ 
                    planet_id: planetId,
                    limit: 1 
                })
                } catch (err) {
                    console.error('[Dashboard] Error loading dashboards:', err)
                    if (isMounted) {
                        setError(err instanceof Error ? err.message : 'Failed to load dashboards')
                        setIsLoading(false)
                    }
                    return
                }
                
                if (!isMounted) return
                if (process.env.NODE_ENV === 'development') {
                    console.log('[Dashboard] Found dashboards:', dashboards.length)
                }
                
                if (dashboards.length > 0) {
                    const dashboardId = dashboards[0].id
                    // Check if we already have this dashboard loaded
                    const cachedDashboard = currentDashboard?.id === dashboardId ? currentDashboard : null
                    
                    // Load dashboard and widgets in parallel for better performance
                    const [dashboard, apiWidgets] = await Promise.all([
                        cachedDashboard ? Promise.resolve(cachedDashboard) : fetchDashboard(dashboardId),
                        dashboardsApi.getWidgets(dashboardId).catch(() => []) // Don't fail if widgets fail
                    ])
                    
                    if (!isMounted) return
                    if (process.env.NODE_ENV === 'development') {
                        console.log('[Dashboard] Dashboard loaded:', dashboard.id)
                    }
                    
                    // Update URL with the loaded dashboard ID
                    router.replace(`/dashboard?id=${dashboard.id}`)
                    
                    // Load canvas settings if available
                    if (dashboard.canvas_settings) {
                        loadSettings(dashboard.canvas_settings)
                    }
                    
                    // Convert and set widgets if we got them (optimized conversion)
                    if (apiWidgets && apiWidgets.length >= 0) {
                        const storeWidgets = convertApiWidgetsToStore(apiWidgets)
                        if (isMounted) {
                            setWidgets(storeWidgets)
                        }
                    }
                } else {
                    // No dashboards, create a default one
                    if (process.env.NODE_ENV === 'development') {
                        console.log('[Dashboard] No dashboards found, creating new one for planet:', planetId)
                    }
                    try {
                        const newDashboard = await dashboardsApi.createDashboard({
                            name: 'My Dashboard',
                            planet_id: planetId,
                        })
                        if (!isMounted) return
                        if (process.env.NODE_ENV === 'development') {
                            console.log('[Dashboard] New dashboard created:', newDashboard.id)
                        }
                        
                        // Dashboard is already in store from createDashboard, use it directly
                        const loadedDashboard = newDashboard
                        
                        // Update URL with the new dashboard ID
                        router.replace(`/dashboard?id=${loadedDashboard.id}`)
                        
                        // Load canvas settings if available
                        if (loadedDashboard.canvas_settings) {
                            loadSettings(loadedDashboard.canvas_settings)
                        }
                        
                        // New dashboard has no widgets, so set empty array
                        if (isMounted) {
                            setWidgets([])
                        }
                    } catch (createErr) {
                        console.error('[Dashboard] Error creating dashboard:', createErr)
                        // If dashboard creation fails, show error but don't break the UI
                        if (isMounted) {
                            const errorMsg = createErr instanceof Error ? createErr.message : 'Failed to create dashboard'
                            console.error('[Dashboard] Dashboard creation failed:', errorMsg)
                            // Check error type for better messaging
                            if (errorMsg.includes('Network error') || errorMsg.includes('Failed to fetch')) {
                                setError('Unable to connect to backend. Please check if the server is running and try again.')
                            } else if (errorMsg.includes('Foreign key') || errorMsg.includes('planet_id') || errorMsg.includes('Planet') && errorMsg.includes('not found')) {
                                setError('Planet not found. Please create a planet first or refresh the page to reload planets.')
                                // Try to reload planets
                                try {
                                    const { fetchPlanets } = usePlanetStore.getState()
                                    await fetchPlanets()
                                } catch (e) {
                                    console.error('Error reloading planets:', e)
                                }
                            } else if (errorMsg.includes('Unauthorized') || errorMsg.includes('401')) {
                                setError('Authentication failed. Please log in again.')
                            } else {
                                setError(`Failed to create dashboard: ${errorMsg}`)
                            }
                            // Still show canvas even if dashboard creation failed
                            setIsLoading(false)
                        }
                        return
                    }
                }
            } catch (err) {
                console.error('[Dashboard] Error loading dashboards:', err)
                if (isMounted) {
                    const errorMsg = err instanceof Error ? err.message : 'Failed to load dashboard'
                    // Check if it's a network error or a real API error
                    if (errorMsg.includes('Network error') || errorMsg.includes('Failed to fetch')) {
                        setError('Unable to connect to backend. Please check if the server is running.')
                    } else if (errorMsg.includes('Foreign key') || errorMsg.includes('planet_id')) {
                        setError('Planet not found. Please refresh the page and try again.')
                    } else if (errorMsg.includes('Unauthorized') || errorMsg.includes('401')) {
                        setError('Authentication failed. Please log in again.')
                    } else {
                        setError(errorMsg)
                    }
                }
            } finally {
                if (isMounted) {
                    setIsLoading(false)
                }
            }
        }

        const loadDashboard = async () => {
            if (!dashboardId) {
                // If no dashboard ID, try to get the first dashboard from current planet
                if (currentPlanet) {
                    await loadDashboardForPlanet(currentPlanet.id)
                } else {
                    // No planet yet, keep loading and wait for it
                    if (process.env.NODE_ENV === 'development') {
                        console.log('[Dashboard] No planet yet, waiting...')
                    }
                    // Don't set isLoading to false here - let the checkPlanet interval handle it
                    return
                }
                return
            }

            // We have a dashboardId - validate it belongs to current planet
            try {
                if (!isMounted) return
                setIsLoading(true)
                setError(null)
                
                // Check if we already have this dashboard loaded
                const cachedDashboard = currentDashboard?.id === dashboardId ? currentDashboard : null
                
                // Load dashboard and widgets in parallel for better performance
                const [dashboard, apiWidgets] = await Promise.all([
                    cachedDashboard ? Promise.resolve(cachedDashboard) : fetchDashboard(dashboardId),
                    dashboardsApi.getWidgets(dashboardId).catch(() => []) // Don't fail if widgets fail
                ])
                
                if (!isMounted) return
                
                // Validate dashboard belongs to current planet
                if (currentPlanet && dashboard.planet_id !== currentPlanet.id) {
                    if (process.env.NODE_ENV === 'development') {
                        console.log('[Dashboard] Dashboard does not belong to current planet, loading planet dashboard instead')
                    }
                    // Clean URL and load dashboard for current planet
                    router.replace('/dashboard')
                    await loadDashboardForPlanet(currentPlanet.id)
                    return
                }
                
                // Load canvas settings if available
                if (dashboard.canvas_settings) {
                    loadSettings(dashboard.canvas_settings)
                }
                
                // Convert and set widgets if we got them (optimized conversion)
                if (apiWidgets && apiWidgets.length >= 0) {
                    const storeWidgets = convertApiWidgetsToStore(apiWidgets)
                    if (isMounted) {
                        setWidgets(storeWidgets)
                    }
                }
            } catch (err) {
                console.error('Error loading dashboard:', err)
                
                // Fallback: if dashboardId é inválido, tente usar o primeiro dashboard do planeta ou criar um novo
                if (isMounted && currentPlanet) {
                    if (process.env.NODE_ENV === 'development') {
                        console.log('[Dashboard] Fallback: loading dashboard for planet')
                    }
                    await loadDashboardForPlanet(currentPlanet.id)
                    return
                }
                
                if (isMounted) {
                    setError(err instanceof Error ? err.message : 'Failed to load dashboard')
                }
            } finally {
                if (isMounted) {
                    setIsLoading(false)
                }
            }
        }

        // Always try to load dashboard if we have a planet or dashboardId
        if (currentPlanet || dashboardId) {
            loadDashboard()
        } else {
            // If no planet, wait for it to be loaded by the layout
            // The layout fetches planets on mount, so we wait a bit
            if (process.env.NODE_ENV === 'development') {
                console.log('[Dashboard] No planet or dashboardId, starting planet check interval')
            }
            const checkPlanet = setInterval(() => {
                if (!isMounted) {
                    clearInterval(checkPlanet)
                    return
                }
                const planet = usePlanetStore.getState().currentPlanet
                if (planet) {
                    if (process.env.NODE_ENV === 'development') {
                        console.log('[Dashboard] Planet found:', planet.id)
                    }
                    clearInterval(checkPlanet)
                    // Reload with the new planet
                    loadDashboardForPlanet(planet.id)
                }
            }, 500) // Reduced from 100ms to 500ms for better performance
            
            // Stop checking after 5 seconds (reduced from 10)
            setTimeout(() => {
                clearInterval(checkPlanet)
                if (isMounted) {
                    // If still no planet after timeout, show canvas anyway (it will work empty)
                    setIsLoading(false)
                }
            }, 5000)
        }

        return () => {
            isMounted = false
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [dashboardId, currentPlanet?.id])

    // Log widgets rendering (only in development, must be before any conditional returns to maintain hook order)
    useEffect(() => {
        if (process.env.NODE_ENV === 'development' && widgets.length > 0) {
            console.log(`[DashboardPage] 📊 Rendering ${widgets.length} widgets`)
        }
    }, [widgets.length, widgets.map(w => w.id).join(',')])

    // Validate all widgets before rendering (memoized for performance)
    const validWidgets = useMemo(() => {
        const valid: typeof widgets = []
        for (let i = 0; i < widgets.length; i++) {
            const widget = widgets[i]
            const hasValidPosition = 
                typeof widget.position?.x === 'number' && !isNaN(widget.position.x) &&
                typeof widget.position?.y === 'number' && !isNaN(widget.position.y)
            const hasValidSize = 
                typeof widget.size?.width === 'number' && !isNaN(widget.size.width) && widget.size.width > 0 &&
                typeof widget.size?.height === 'number' && !isNaN(widget.size.height) && widget.size.height > 0
            
            if (hasValidPosition && hasValidSize) {
                valid.push(widget)
            } else if (process.env.NODE_ENV === 'development') {
                console.error(`[DashboardPage] ❌ Widget ${widget.id} has invalid position or size`)
            }
        }
        return valid
    }, [widgets])

    // Show loading while dashboard is being loaded/created
    if (isLoading) {
        return (
            <div className="w-full h-full flex items-center justify-center">
                <div className="text-center">
                    <Loader2 className="h-8 w-8 animate-spin mx-auto text-blue-500" />
                    <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">Loading dashboard...</p>
                </div>
            </div>
        )
    }

    // Show error if there's one
    if (error) {
        const isAuthError = error.includes('Authentication') || error.includes('Unauthorized') || error.includes('401')
        return (
            <div className="w-full h-full flex items-center justify-center">
                <div className="text-center max-w-md">
                    <p className="text-red-500 mb-4">{error}</p>
                    <div className="flex gap-2 justify-center">
                        {isAuthError ? (
                            <button 
                                onClick={() => {
                                    // Clear tokens and redirect to login
                                    localStorage.removeItem('access_token')
                                    localStorage.removeItem('refresh_token')
                                    window.location.href = '/login'
                                }} 
                                className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
                            >
                                Go to Login
                            </button>
                        ) : (
                            <button 
                                onClick={() => window.location.reload()} 
                                className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
                            >
                                Retry
                            </button>
                        )}
                    </div>
                </div>
            </div>
        )
    }

    // Always render canvas and toolbar, even if dashboard is still loading
    // The canvas will work with empty widgets array
    
    return (
        <div className="w-full h-full">
            <Toolbar />
            <Canvas>
                {validWidgets.map((widget) => (
                    <WidgetContainer key={widget.id} widget={widget} />
                ))}
            </Canvas>
        </div>
    )
}

export default function DashboardPage() {
    return (
        <Suspense fallback={
            <div className="w-full h-full flex items-center justify-center">
                <div className="text-center">
                    <Loader2 className="h-8 w-8 animate-spin mx-auto text-blue-500" />
                    <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">Loading...</p>
                </div>
            </div>
        }>
            <DashboardContent />
        </Suspense>
    )
}
