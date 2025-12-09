"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"
import { Topbar } from "@/components/layout/topbar"
import { RightSidebar } from "@/components/layout/right-sidebar"
import { HelpButton } from "@/components/layout/help-button"
import { PipelineOverlay } from "@/components/dashboard/pipeline-overlay"
import { TemplatesDialog } from "@/components/dashboard/templates-dialog"
import { SettingsDialog } from "@/components/dashboard/settings-dialog"
import { GalaxieSidebar } from "@/components/layout/galaxie/galaxie-sidebar"
import { useSidebarStore } from "@/store/sidebar-store"
import { useUserStore } from "@/store/user-store"
import { usePlanetStore } from "@/store/planet-store"
import { cn } from "@/lib/utils"

export default function DashboardLayout({
    children,
}: {
    children: React.ReactNode
}) {
    const { isOpen: isSidebarOpen } = useSidebarStore()
    const { isAuthenticated, checkSession, isLoading } = useUserStore()
    const { fetchPlanets } = usePlanetStore()
    const router = useRouter()

    // Check session on mount
    useEffect(() => {
        checkSession()
    }, [checkSession])

    // Fetch workspaces when authenticated
    useEffect(() => {
        if (isAuthenticated && !isLoading) {
            fetchPlanets().catch(console.error)
        }
    }, [isAuthenticated, isLoading, fetchPlanets])

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
        <div className="h-screen overflow-hidden bg-background relative flex">
            {/* Galaxie Sidebar - Only render when authenticated */}
            {isAuthenticated && <GalaxieSidebar />}
            {/* Main Content Area */}
            <div className="flex-1 flex flex-col min-w-0">
                {/* Floating Topbar */}
                {isAuthenticated && <Topbar />}
                <main className="relative flex-1 overflow-hidden">
                    {children}
                </main>
            </div>
            {/* RightSidebar as overlay */}
            {isAuthenticated && <RightSidebar />}
            {/* Pipeline overlay */}
            {isAuthenticated && <PipelineOverlay />}
            {/* Templates Dialog */}
            {isAuthenticated && <TemplatesDialog />}
            {/* Settings Dialog */}
            {isAuthenticated && <SettingsDialog />}
            {/* Settings Button */}
            {isAuthenticated && <HelpButton />}
        </div>
    )
}
