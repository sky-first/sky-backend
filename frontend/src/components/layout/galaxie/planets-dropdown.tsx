"use client"

import { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Sparkles, Plus, Copy, Move, Download, ChevronRight } from "lucide-react"
import { usePlanetStore, type Planet } from "@/store/planet-store"
import { useRecentsStore } from "@/store/recents-store"
import { useStarredStore } from "@/store/starred-store"
import { useRouter } from "next/navigation"
import { cn } from "@/lib/utils"
import { Star } from "lucide-react"
import { dashboardsApi } from "@/lib/api/dashboards"

interface PlanetsDropdownProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onClose?: () => void
}

export function PlanetsDropdown({ isOpen, onOpenChange, onClose }: PlanetsDropdownProps) {
  const router = useRouter()
  const { planets, currentPlanet, fetchPlanets, switchPlanet, isLoading } = usePlanetStore()
  const { addRecent } = useRecentsStore()
  const { toggleStar, isStarred } = useStarredStore()
  const [showCreateDialog, setShowCreateDialog] = useState(false)

  useEffect(() => {
    if (isOpen && planets.length === 0) {
      fetchPlanets().catch(console.error)
    }
  }, [isOpen, planets.length, fetchPlanets])

  const handlePlanetClick = async (planet: Planet) => {
    try {
      await switchPlanet(planet.id)
      addRecent({
        id: planet.id,
        type: 'planet',
        name: planet.name,
        description: planet.description,
        icon: planet.icon,
        color: planet.color,
      })
      onOpenChange(false)
      onClose?.()
      router.push("/dashboard")
    } catch (error) {
      console.error('Error switching planet:', error)
    }
  }

  const handleStarClick = (e: React.MouseEvent, planet: Planet) => {
    e.stopPropagation()
    toggleStar({
      id: planet.id,
      type: 'planet',
      name: planet.name,
      description: planet.description,
      icon: planet.icon,
      color: planet.color,
    })
  }

  const handleDuplicate = async (e: React.MouseEvent, planet: Planet) => {
    e.stopPropagation()
    if (!planet) return
    try {
      const dashboards = await dashboardsApi.listDashboards({ planet_id: planet.id })
      if (dashboards.length > 0) {
        const dashboard = dashboards[0]
        await dashboardsApi.duplicateDashboard(dashboard.id, { name: `${dashboard.name} (Copy)` })
        await fetchPlanets()
      }
    } catch (error) {
      console.error('Error duplicating:', error)
    }
  }

  const handleMoveTo = (e: React.MouseEvent, planet: Planet) => {
    e.stopPropagation()
    // TODO: Implement move to functionality
    console.log("Move to:", planet.name)
  }

  const handleExport = async (e: React.MouseEvent, planet: Planet) => {
    e.stopPropagation()
    if (!planet) return
    try {
      const dashboards = await dashboardsApi.listDashboards({ planet_id: planet.id })
      if (dashboards.length > 0) {
        const dashboard = dashboards[0]
        const exportData = await dashboardsApi.exportDashboard(dashboard.id)
        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${dashboard.name}.json`
        a.click()
        URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error('Error exporting:', error)
    }
  }

  const handleViewAll = () => {
    onOpenChange(false)
    onClose?.()
    router.push("/dashboard")
  }

  if (!isOpen) return null

  return (
    <>
      <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -10 }}
          transition={{ duration: 0.2 }}
          className={cn(
            "absolute left-full top-0 ml-2 w-64",
            "bg-white dark:bg-gray-900",
            "rounded-xl shadow-xl",
            "border border-gray-200 dark:border-gray-800",
            "overflow-hidden z-[60]",
            "pointer-events-auto"
          )}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="p-3 space-y-1">
            {planets.slice(0, 3).map((planet) => {
              const starred = isStarred(planet.id, 'planet')
              
              return (
                <div key={planet.id} className="space-y-1">
                  <button
                    onClick={() => handlePlanetClick(planet)}
                    className={cn(
                      "w-full text-left px-3 py-2 rounded-lg",
                      "transition-all duration-200",
                      "hover:bg-gray-100 dark:hover:bg-gray-800",
                      "text-gray-700 dark:text-gray-300"
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm flex-1">{planet.name}</span>
                      <button
                        onClick={(e) => handleStarClick(e, planet)}
                        className={cn(
                          "p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700",
                          starred && "text-yellow-500"
                        )}
                      >
                        <Star
                          className={cn(
                            "w-3 h-3",
                            starred ? "fill-yellow-500" : "text-gray-400"
                          )}
                        />
                      </button>
                    </div>
                  </button>
                  
                  {/* Actions for this planet */}
                  <div className="pl-3 space-y-0.5">
                    <button
                      onClick={(e) => handleDuplicate(e, planet)}
                      className={cn(
                        "w-full text-left px-2 py-1 rounded text-xs",
                        "hover:bg-gray-100 dark:hover:bg-gray-800",
                        "text-gray-600 dark:text-gray-400"
                      )}
                    >
                      Duplicate
                    </button>
                    <button
                      onClick={(e) => handleMoveTo(e, planet)}
                      className={cn(
                        "w-full text-left px-2 py-1 rounded text-xs",
                        "hover:bg-gray-100 dark:hover:bg-gray-800",
                        "text-gray-600 dark:text-gray-400"
                      )}
                    >
                      Move to
                    </button>
                    <button
                      onClick={(e) => handleExport(e, planet)}
                      className={cn(
                        "w-full text-left px-2 py-1 rounded text-xs",
                        "hover:bg-gray-100 dark:hover:bg-gray-800",
                        "text-gray-600 dark:text-gray-400"
                      )}
                    >
                      Export
                    </button>
                  </div>
                </div>
              )
            })}
            
            {/* New Planet */}
            <button
              onClick={() => setShowCreateDialog(true)}
              className={cn(
                "w-full text-left px-3 py-2 rounded-lg",
                "transition-all duration-200",
                "hover:bg-gray-100 dark:hover:bg-gray-800",
                "text-blue-600 dark:text-blue-400",
                "font-medium"
              )}
            >
              <div className="flex items-center gap-2">
                <Plus className="w-4 h-4" />
                <span className="text-sm">New planet</span>
              </div>
            </button>
            
            {/* All Planets */}
            <button
              onClick={handleViewAll}
              className={cn(
                "w-full text-left px-3 py-2 rounded-lg",
                "transition-all duration-200",
                "hover:bg-gray-100 dark:hover:bg-gray-800",
                "text-gray-600 dark:text-gray-400",
                "text-sm"
              )}
            >
              All planets
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
    
    {/* Create Planet Dialog */}
    <CreatePlanetDialog
      open={showCreateDialog}
      onOpenChange={setShowCreateDialog}
    />
    </>
  )
}

