"use client"

import { useEffect, useCallback, lazy, Suspense } from "react"
import { useRouter } from "next/navigation"
import { Topbar } from "@/components/layout/topbar"
import { ContextBreadcrumb } from "@/components/layout/context-breadcrumb"
import { RightSidebar } from "@/components/layout/right-sidebar"
import { HelpButton } from "@/components/layout/help-button"
import { GalaxieSidebar } from "@/components/layout/galaxie/galaxie-sidebar"
import { useSidebarStore } from "@/store/sidebar-store"
import { useUserStore } from "@/store/user-store"
import { usePlanetStore } from "@/store/planet-store"
import { cn } from "@/lib/utils"

// Lazy load heavy components to improve initial load time
const PipelineOverlay = lazy(() => import("@/components/dashboard/pipeline-overlay").then(m => ({ default: m.PipelineOverlay })))
const TemplatesDialog = lazy(() => import("@/components/dashboard/templates-dialog").then(m => ({ default: m.TemplatesDialog })))
const SettingsDialog = lazy(() => import("@/components/dashboard/settings-dialog").then(m => ({ default: m.SettingsDialog })))

export default function DashboardLayout({
    children,
}: {
    children: React.ReactNode
}) {
    // Use Zustand selectors to avoid unnecessary re-renders
    const isSidebarOpen = useSidebarStore(state => state.isOpen)
    const isAuthenticated = useUserStore(state => state.isAuthenticated)
    const checkSession = useUserStore(state => state.checkSession)
    const isLoading = useUserStore(state => state.isLoading)
    const fetchPlanets = usePlanetStore(state => state.fetchPlanets)
    const router = useRouter()

    // Memoize checkSession callback
    const handleCheckSession = useCallback(() => {
        checkSession()
    }, [checkSession])

    // Memoize fetchPlanets callback
    const handleFetchPlanets = useCallback(() => {
        if (isAuthenticated && !isLoading) {
            fetchPlanets().catch(console.error)
        }
    }, [isAuthenticated, isLoading, fetchPlanets])

    // Check session on mount
    useEffect(() => {
        handleCheckSession()
    }, [handleCheckSession])

    // Fetch workspaces when authenticated
    useEffect(() => {
        handleFetchPlanets()
    }, [handleFetchPlanets])

    // Redirect to login if not authenticated (after loading)
    useEffect(() => {
        if (!isLoading && !isAuthenticated) {
            router.push("/login")
        }
    }, [isAuthenticated, isLoading, router])

    if (isLoading) {
        return (
            <div className="h-screen flex items-center justify-center">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto"></div>
                    <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">Loading...</p>
                </div>
            </div>
        )
    }

    if (!isAuthenticated) {
        return null
    }

    return (
        <div className="h-screen overflow-hidden bg-background relative">
            {/* Galaxie Sidebar - Only render when authenticated */}
            {isAuthenticated && <GalaxieSidebar />}
            {/* Floating Topbar */}
            {isAuthenticated && <Topbar />}
            {/* Context Breadcrumb - Center top */}
            {isAuthenticated && <ContextBreadcrumb />}
            <main className="relative flex h-screen">
                <div className="flex-1 relative">
                    {children}
                </div>
            </main>
            {/* RightSidebar as overlay */}
            {isAuthenticated && <RightSidebar />}
            {/* Pipeline overlay - lazy loaded */}
            {isAuthenticated && (
                <Suspense fallback={null}>
                    <PipelineOverlay />
                </Suspense>
            )}
            {/* Templates Dialog - lazy loaded */}
            {isAuthenticated && (
                <Suspense fallback={null}>
                    <TemplatesDialog />
                </Suspense>
            )}
            {/* Settings Dialog - lazy loaded */}
            {isAuthenticated && (
                <Suspense fallback={null}>
                    <SettingsDialog />
                </Suspense>
            )}
            {/* Settings Button */}
            {isAuthenticated && <HelpButton />}
        </div>
    )
}
