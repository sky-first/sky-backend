"use client"

import { useEffect, useState, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { Canvas } from "@/components/dashboard/canvas"
import { WidgetContainer } from "@/components/dashboard/widget-container"
import { Toolbar } from "@/components/dashboard/toolbar"
import { useWidgetStore } from "@/store/widget-store"
import { useDashboardStore } from "@/store/dashboard-store"
import { usePlanetStore } from "@/store/planet-store"
import { dashboardsApi } from "@/lib/api/dashboards"
import { Loader2 } from "lucide-react"

function DashboardContent() {
    const searchParams = useSearchParams()
    const dashboardId = searchParams.get('id')
    
    const { widgets, setWidgets } = useWidgetStore()
    const { currentDashboard, fetchDashboard, setCurrentDashboard } = useDashboardStore()
    const { currentPlanet } = usePlanetStore()
    
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    // Load dashboard and widgets
    useEffect(() => {
        let isMounted = true

        const loadWidgets = async (dashboardId: string) => {
            try {
                const apiWidgets = await dashboardsApi.getDashboardWidgets(dashboardId)
                if (!isMounted) return
                
                // Convert API widgets to store format
                const storeWidgets = apiWidgets.map((w) => ({
                    id: w.id,
                    type: w.type as 'chart' | 'kpi' | 'table' | 'ai-box' | 'text',
                    title: w.title,
                    position: w.position,
                    size: w.size,
                    data: w.data || {},
                }))
                setWidgets(storeWidgets)
            } catch (err) {
                console.error('Error loading widgets:', err)
                // Don't set error here, just log it - widgets might be empty
            }
        }

        const loadDashboard = async () => {
            if (!dashboardId) {
                // If no dashboard ID, try to get the first dashboard from current planet
                if (currentPlanet) {
                    try {
                        if (!isMounted) return
                        setIsLoading(true)
                        setError(null)
                        
                        const dashboards = await dashboardsApi.listDashboards({ 
                            planet_id: currentPlanet.id,
                            limit: 1 
                        })
                        
                        if (!isMounted) return
                        
                        if (dashboards.length > 0) {
                            const dashboard = await fetchDashboard(dashboards[0].id)
                            if (!isMounted) return
                            await loadWidgets(dashboard.id)
                        } else {
                            // No dashboards, create a default one
                            const newDashboard = await dashboardsApi.createDashboard({
                                name: 'My Dashboard',
                                planet_id: currentPlanet.id,
                            })
                            if (!isMounted) return
                            await fetchDashboard(newDashboard.id)
                            await loadWidgets(newDashboard.id)
                        }
                    } catch (err) {
                        console.error('Error loading dashboards:', err)
                        if (isMounted) {
                            setError(err instanceof Error ? err.message : 'Failed to load dashboard')
                        }
                    } finally {
                        if (isMounted) {
                            setIsLoading(false)
                        }
                    }
                } else {
                    if (isMounted) {
                        setIsLoading(false)
                    }
                }
                return
            }

            try {
                if (!isMounted) return
                setIsLoading(true)
                setError(null)
                
                await fetchDashboard(dashboardId)
                if (!isMounted) return
                await loadWidgets(dashboardId)
            } catch (err) {
                console.error('Error loading dashboard:', err)
                if (isMounted) {
                    setError(err instanceof Error ? err.message : 'Failed to load dashboard')
                }
            } finally {
                if (isMounted) {
                    setIsLoading(false)
                }
            }
        }

        if (currentPlanet || dashboardId) {
            loadDashboard()
        } else {
            setIsLoading(false)
        }

        return () => {
            isMounted = false
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [dashboardId, currentPlanet?.id])

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

    if (error) {
        return (
            <div className="w-full h-full flex items-center justify-center">
                <div className="text-center">
                    <p className="text-red-500">{error}</p>
                </div>
            </div>
        )
    }

    if (!currentDashboard) {
        return (
            <div className="w-full h-full flex items-center justify-center">
                <div className="text-center">
                    <p className="text-gray-600 dark:text-gray-400">No dashboard selected</p>
                </div>
            </div>
        )
    }

    return (
        <div className="w-full h-full">
            <Toolbar />
            <Canvas>
                {widgets.map((widget) => (
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
