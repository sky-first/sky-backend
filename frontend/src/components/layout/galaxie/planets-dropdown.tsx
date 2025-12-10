"use client"

import { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Sparkles, Plus, Copy, Move, Download, ChevronRight, Search, Star } from "lucide-react"
import { usePlanetStore, type Planet } from "@/store/planet-store"
import { useRecentsStore } from "@/store/recents-store"
import { useStarredStore } from "@/store/starred-store"
import { useRouter } from "next/navigation"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { dashboardsApi } from "@/lib/api/dashboards"
import { CreatePlanetDialog } from "@/components/workspaces/create-workspace-dialog"
import { Loader2 } from "lucide-react"

interface PlanetsDropdownProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onClose?: () => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
}

export function PlanetsDropdown({ isOpen, onOpenChange, onClose, onMouseEnter, onMouseLeave }: PlanetsDropdownProps) {
  const router = useRouter()
  const { planets, currentPlanet, fetchPlanets, switchPlanet, isLoading } = usePlanetStore()
  const { addRecent } = useRecentsStore()
  const { toggleStar, isStarred } = useStarredStore()
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const timeoutRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    if (isOpen && planets.length === 0) {
      fetchPlanets().catch(console.error)
    }
  }, [isOpen, planets.length, fetchPlanets])

  // Cancel timeout when dialog opens and prevent dropdown from closing
  useEffect(() => {
    if (showCreateDialog) {
      // Cancel any pending timeout to keep dropdown open
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }
    }
  }, [showCreateDialog])

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
    }
  }, [])

  const filteredPlanets = planets.filter(planet =>
    planet.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    planet.description?.toLowerCase().includes(searchQuery.toLowerCase())
  )

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

  const handleDuplicate = async () => {
    if (!currentPlanet) return
    try {
      const dashboards = await dashboardsApi.listDashboards({ planet_id: currentPlanet.id })
      if (dashboards.length > 0) {
        const dashboard = dashboards[0]
        await dashboardsApi.duplicateDashboard(dashboard.id, { name: `${dashboard.name} (Copy)` })
        await fetchPlanets()
      }
    } catch (error) {
      console.error('Error duplicating:', error)
    }
  }

  const handleMoveTo = () => {
    if (!currentPlanet) return
    // TODO: Implement move to functionality
    console.log("Move to:", currentPlanet.name)
  }

  const handleExport = async () => {
    if (!currentPlanet) return
    try {
      const dashboards = await dashboardsApi.listDashboards({ planet_id: currentPlanet.id })
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

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map(n => n[0])
      .join('')
      .slice(0, 2)
      .toUpperCase()
  }

  const getAvatarColor = (color?: string) => {
    if (!color) return 'bg-gray-500'
    const colorMap: Record<string, string> = {
      blue: 'bg-blue-500',
      green: 'bg-green-500',
      purple: 'bg-purple-500',
      pink: 'bg-pink-500',
      orange: 'bg-orange-500',
      red: 'bg-red-500',
      teal: 'bg-teal-500',
      indigo: 'bg-indigo-500',
    }
    return colorMap[color.toLowerCase()] || 'bg-gray-500'
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
            "w-80 flex flex-col flex-shrink-0",
            "bg-white dark:bg-gray-900",
            "border-l border-gray-200 dark:border-gray-800",
            "overflow-hidden",
            "pointer-events-auto"
          )}
          onClick={(e) => e.stopPropagation()}
          onMouseEnter={() => {
            // Cancel any pending timeout
            if (timeoutRef.current) {
              clearTimeout(timeoutRef.current)
              timeoutRef.current = null
            }
            // Call parent handler
            onMouseEnter?.()
          }}
          onMouseLeave={() => {
            // Don't close dropdown if dialog is open
            if (showCreateDialog) {
              return
            }
            // Store timeout in local ref so we can cancel it
            timeoutRef.current = setTimeout(() => {
              onOpenChange(false)
            }, 200)
            // Call parent handler
            onMouseLeave?.()
          }}
        >
          {/* Header */}
          <div className="p-5 border-b border-gray-200 dark:border-gray-800">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
              Planets
            </h2>
            
            {/* Search Bar */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <Input
                type="text"
                placeholder="Filter planets..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className={cn(
                  "pl-9 h-9 w-full rounded-lg border-2 border-blue-500",
                  "bg-white dark:bg-gray-800",
                  "text-gray-900 dark:text-white",
                  "placeholder:text-gray-400 dark:placeholder:text-gray-500",
                  "focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                )}
              />
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-4">
            {/* PLANETS Section */}
            <div className="mb-6">
              <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3 px-2">
                PLANETS
              </div>
              <div className="space-y-1">
                {isLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
                  </div>
                ) : filteredPlanets.length === 0 ? (
                  <div className="px-2 py-4 text-center text-sm text-gray-500 dark:text-gray-400">
                    No planets found
                  </div>
                ) : (
                  filteredPlanets.map((planet) => {
                    const starred = isStarred(planet.id, 'planet')
                    const initials = planet.icon || getInitials(planet.name)
                    const avatarColor = getAvatarColor(planet.color)
                    
                    return (
                      <div key={planet.id} className="group">
                        <button
                          onClick={() => handlePlanetClick(planet)}
                          className={cn(
                            "w-full text-left px-3 py-2.5 rounded-lg",
                            "transition-all duration-200",
                            "hover:bg-gray-50 dark:hover:bg-gray-800",
                            "flex items-center gap-3",
                            currentPlanet?.id === planet.id && "bg-blue-50 dark:bg-blue-900/20"
                          )}
                        >
                          <div className={cn(
                            "w-8 h-8 rounded-full flex items-center justify-center",
                            "text-white text-xs font-semibold",
                            avatarColor
                          )}>
                            {initials}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium text-gray-900 dark:text-white truncate">
                              {planet.name}
                            </div>
                            {planet.description && (
                              <div className="text-xs text-gray-500 dark:text-gray-400 truncate">
                                {planet.description}
                              </div>
                            )}
                          </div>
                          <button
                            onClick={(e) => handleStarClick(e, planet)}
                            className={cn(
                              "p-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity",
                              starred && "opacity-100 text-yellow-500"
                            )}
                          >
                            <Star
                              className={cn(
                                "w-4 h-4",
                                starred ? "fill-yellow-500 text-yellow-500" : "text-gray-400"
                              )}
                            />
                          </button>
                        </button>
                      </div>
                    )
                  })
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="space-y-1 pt-4 border-t border-gray-200 dark:border-gray-800">
              {/* Duplicate */}
              <button
                onClick={handleDuplicate}
                disabled={!currentPlanet}
                className={cn(
                  "w-full text-left px-3 py-2 rounded-lg",
                  "transition-all duration-200",
                  "hover:bg-gray-50 dark:hover:bg-gray-800",
                  "text-gray-700 dark:text-gray-300",
                  "text-sm",
                  "flex items-center gap-2",
                  !currentPlanet && "opacity-50 cursor-not-allowed"
                )}
              >
                <Copy className="w-4 h-4" />
                Duplicate
              </button>

              {/* Move to */}
              <button
                onClick={handleMoveTo}
                disabled={!currentPlanet}
                className={cn(
                  "w-full text-left px-3 py-2 rounded-lg",
                  "transition-all duration-200",
                  "hover:bg-gray-50 dark:hover:bg-gray-800",
                  "text-gray-700 dark:text-gray-300",
                  "text-sm",
                  "flex items-center gap-2",
                  !currentPlanet && "opacity-50 cursor-not-allowed"
                )}
              >
                <Move className="w-4 h-4" />
                Move to
              </button>

              {/* Export */}
              <button
                onClick={handleExport}
                disabled={!currentPlanet}
                className={cn(
                  "w-full text-left px-3 py-2 rounded-lg",
                  "transition-all duration-200",
                  "hover:bg-gray-50 dark:hover:bg-gray-800",
                  "text-gray-700 dark:text-gray-300",
                  "text-sm",
                  "flex items-center gap-2",
                  !currentPlanet && "opacity-50 cursor-not-allowed"
                )}
              >
                <Download className="w-4 h-4" />
                Export
              </button>

              {/* New Planet */}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setShowCreateDialog(true)
                }}
                className={cn(
                  "w-full text-left px-3 py-2 rounded-lg",
                  "transition-all duration-200",
                  "hover:bg-gray-50 dark:hover:bg-gray-800",
                  "text-blue-600 dark:text-blue-400",
                  "font-medium text-sm",
                  "flex items-center gap-2"
                )}
              >
                <Plus className="w-4 h-4" />
                New Planet
              </button>
              
              {/* All Planets */}
              <button
                onClick={handleViewAll}
                className={cn(
                  "w-full text-left px-3 py-2 rounded-lg",
                  "transition-all duration-200",
                  "hover:bg-gray-50 dark:hover:bg-gray-800",
                  "text-gray-600 dark:text-gray-400",
                  "text-sm"
                )}
              >
                All Planets
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
    
    {/* Create Planet Dialog */}
    <CreatePlanetDialog
      open={showCreateDialog}
      onOpenChange={(open) => {
        setShowCreateDialog(open)
        // When dialog closes, cancel any pending timeout
        if (!open && timeoutRef.current) {
          clearTimeout(timeoutRef.current)
          timeoutRef.current = null
        }
      }}
    />
    </>
  )
}

