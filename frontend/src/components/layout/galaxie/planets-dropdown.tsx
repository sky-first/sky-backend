"use client"

import { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Sparkles, Plus, Copy, Move, Download, ChevronRight, Search, Star, MoreVertical, Edit2, Trash2, X, CheckCircle2 } from "lucide-react"
import { usePlanetStore, type Planet } from "@/store/planet-store"
import { useRecentsStore } from "@/store/recents-store"
import { useStarredStore } from "@/store/starred-store"
import { useRouter } from "next/navigation"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { dashboardsApi } from "@/lib/api/dashboards"
import { CreatePlanetDialog } from "@/components/workspaces/create-workspace-dialog"
import { Loader2 } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

interface PlanetsDropdownProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onClose?: () => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
  onCloseSidebar?: () => void
}

export function PlanetsDropdown({ isOpen, onOpenChange, onClose, onMouseEnter, onMouseLeave, onCloseSidebar }: PlanetsDropdownProps) {
  const router = useRouter()
  const { planets, currentPlanet, fetchPlanets, switchPlanet, updatePlanet, deletePlanet, isLoading } = usePlanetStore()
  const { addRecent } = useRecentsStore()
  const { toggleStar, isStarred } = useStarredStore()
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const [editingPlanet, setEditingPlanet] = useState<Planet | null>(null)
  const [deletingPlanet, setDeletingPlanet] = useState<Planet | null>(null)
  const [editName, setEditName] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showPlanetActions, setShowPlanetActions] = useState<Planet | null>(null)
  const [showMoveToDialog, setShowMoveToDialog] = useState(false)
  const [selectedTargetPlanet, setSelectedTargetPlanet] = useState<Planet | null>(null)
  const [isMoving, setIsMoving] = useState(false)
  const timeoutRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    if (isOpen && planets.length === 0) {
      fetchPlanets().catch((error) => {
        console.error('Error fetching planets:', error)
        // Error is handled in the store, but we log it here for debugging
      })
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
    setShowMoveToDialog(true)
    setShowPlanetActions(null)
  }

  const handleMoveToConfirm = async () => {
    if (!currentPlanet || !selectedTargetPlanet) return
    
    setIsMoving(true)
    try {
      // Get current dashboard for this planet
      const dashboards = await dashboardsApi.listDashboards({ planet_id: currentPlanet.id })
      
      if (dashboards.length === 0) {
        alert('No dashboard found for this planet')
        return
      }

      // Move all dashboards to the target planet
      const movePromises = dashboards.map(dashboard => 
        dashboardsApi.updateDashboard(dashboard.id, { planet_id: selectedTargetPlanet.id })
      )
      
      await Promise.all(movePromises)
      
      // Switch to target planet
      await switchPlanet(selectedTargetPlanet.id)
      
      // Refresh planets list
      await fetchPlanets()
      
      setShowMoveToDialog(false)
      setSelectedTargetPlanet(null)
      onOpenChange(false)
      onClose?.()
      
      // Navigate to dashboard
      router.push("/dashboard")
    } catch (error) {
      console.error('Error moving planet:', error)
      alert(`Failed to move: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setIsMoving(false)
    }
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

  const handleMenuClick = (planet: Planet, e: React.MouseEvent) => {
    e.stopPropagation()
    setShowPlanetActions(planet)
  }

  const handleRenameClick = () => {
    if (!showPlanetActions) return
    setEditingPlanet(showPlanetActions)
    setEditName(showPlanetActions.name)
    setShowPlanetActions(null)
  }

  const handleRenameSubmit = async () => {
    if (!editingPlanet || !editName.trim()) return
    
    setIsSubmitting(true)
    try {
      await updatePlanet(editingPlanet.id, { name: editName.trim() })
      await fetchPlanets()
      setEditingPlanet(null)
      setEditName("")
    } catch (error) {
      console.error('Error renaming planet:', error)
      alert('Erro ao renomear planet. Por favor, tente novamente.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDeleteClick = () => {
    if (!showPlanetActions) return
    setDeletingPlanet(showPlanetActions)
    setShowPlanetActions(null)
  }

  const handleDeleteConfirm = async () => {
    if (!deletingPlanet) return
    
    setIsSubmitting(true)
    try {
      await deletePlanet(deletingPlanet.id)
      await fetchPlanets()
      setDeletingPlanet(null)
      // If deleted planet was current, switch to first available
      if (currentPlanet?.id === deletingPlanet.id) {
        const remainingPlanets = planets.filter(p => p.id !== deletingPlanet.id)
        if (remainingPlanets.length > 0) {
          await switchPlanet(remainingPlanets[0].id)
          router.push("/dashboard")
        }
      }
    } catch (error) {
      console.error('Error deleting planet:', error)
      alert('Erro ao deletar planet. Por favor, tente novamente.')
    } finally {
      setIsSubmitting(false)
    }
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
            // Don't close dropdown if any dialog or sidebar is open
            if (showCreateDialog || editingPlanet || deletingPlanet || showPlanetActions) {
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
                      <div key={planet.id} className="group relative">
                        <div
                          onClick={() => handlePlanetClick(planet)}
                          className={cn(
                            "w-full text-left px-3 py-2.5 rounded-lg",
                            "transition-all duration-200",
                            "hover:bg-gray-50 dark:hover:bg-gray-800",
                            "flex items-center gap-3",
                            "cursor-pointer",
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
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleStarClick(e, planet)
                              }}
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
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleMenuClick(planet, e)
                              }}
                              className={cn(
                                "p-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity",
                                "text-gray-400 hover:text-gray-600 dark:hover:text-gray-300",
                                showPlanetActions?.id === planet.id && "opacity-100"
                              )}
                            >
                              <MoreVertical className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                        
                        {/* Planet Actions Sidetip - positioned below this item */}
                        <AnimatePresence>
                          {showPlanetActions?.id === planet.id && (
                            <motion.div
                              initial={{ opacity: 0, y: -5 }}
                              animate={{ opacity: 1, y: 0 }}
                              exit={{ opacity: 0, y: -5 }}
                              transition={{ duration: 0.15 }}
                              className={cn(
                                "absolute right-0 top-full mt-2",
                                "w-40",
                                "bg-white dark:bg-gray-800",
                                "border border-gray-200 dark:border-gray-700",
                                "rounded-lg shadow-lg",
                                "overflow-hidden",
                                "pointer-events-auto",
                                "z-50"
                              )}
                              onClick={(e) => e.stopPropagation()}
                              onMouseEnter={() => {
                                // Cancel any pending timeout
                                if (timeoutRef.current) {
                                  clearTimeout(timeoutRef.current)
                                  timeoutRef.current = null
                                }
                              }}
                              onMouseLeave={() => {
                                // Close sidetip when mouse leaves
                                setTimeout(() => {
                                  setShowPlanetActions(null)
                                }, 150)
                              }}
                            >
                              {/* Actions */}
                              <div className="py-1">
                                <button
                                  onClick={handleRenameClick}
                                  className={cn(
                                    "w-full text-left px-3 py-2",
                                    "transition-colors duration-150",
                                    "hover:bg-gray-50 dark:hover:bg-gray-700",
                                    "text-gray-700 dark:text-gray-300",
                                    "text-sm",
                                    "flex items-center gap-2"
                                  )}
                                >
                                  <Edit2 className="w-3.5 h-3.5" />
                                  <span>Rename</span>
                                </button>

                                <button
                                  onClick={handleDeleteClick}
                                  className={cn(
                                    "w-full text-left px-3 py-2",
                                    "transition-colors duration-150",
                                    "hover:bg-red-50 dark:hover:bg-red-900/20",
                                    "text-red-600 dark:text-red-400",
                                    "text-sm",
                                    "flex items-center gap-2"
                                  )}
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                  <span>Delete</span>
                                </button>
                              </div>
                            </motion.div>
                          )}
                        </AnimatePresence>
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
                  // Don't close sidebar immediately - let it stay open while dialog is open
                  // The sidebar will close automatically when mouse leaves if no dialog is open
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

    {/* Rename Planet Dialog */}
    <Dialog open={!!editingPlanet} onOpenChange={(open) => {
      if (!open) {
        setEditingPlanet(null)
        setEditName("")
      }
    }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename Planet</DialogTitle>
          <DialogDescription>
            Enter a new name for this planet.
          </DialogDescription>
        </DialogHeader>
        <div className="py-4">
          <Input
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            placeholder="Planet name"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                handleRenameSubmit()
              }
            }}
            autoFocus
          />
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              setEditingPlanet(null)
              setEditName("")
            }}
            disabled={isSubmitting}
          >
            Cancel
          </Button>
          <Button
            onClick={handleRenameSubmit}
            disabled={!editName.trim() || isSubmitting}
          >
            {isSubmitting ? "Saving..." : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    {/* Delete Planet Dialog */}
    <Dialog open={!!deletingPlanet} onOpenChange={(open) => {
      if (!open) {
        setDeletingPlanet(null)
      }
    }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete Planet</DialogTitle>
          <DialogDescription>
            Are you sure you want to delete "{deletingPlanet?.name}"? This action cannot be undone and will delete all dashboards and data associated with this planet.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => setDeletingPlanet(null)}
            disabled={isSubmitting}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDeleteConfirm}
            disabled={isSubmitting}
          >
            {isSubmitting ? "Deleting..." : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    {/* Move To Dialog */}
    <Dialog open={showMoveToDialog} onOpenChange={setShowMoveToDialog}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Move to Planet</DialogTitle>
          <DialogDescription>
            Select a planet to move "{currentPlanet?.name}" dashboards to.
          </DialogDescription>
        </DialogHeader>
        <div className="py-4">
          <div className="space-y-2 max-h-[300px] overflow-y-auto">
            {planets
              .filter(p => p.id !== currentPlanet?.id)
              .map((planet) => (
                <button
                  key={planet.id}
                  onClick={() => setSelectedTargetPlanet(planet)}
                  className={cn(
                    "w-full text-left px-4 py-3 rounded-lg border transition-all",
                    selectedTargetPlanet?.id === planet.id
                      ? "border-primary bg-primary/10"
                      : "border-border hover:bg-accent"
                  )}
                >
                  <div className="flex items-center gap-3">
                    <div
                      className="w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-semibold"
                      style={{ backgroundColor: planet.color }}
                    >
                      {planet.icon || planet.name.charAt(0).toUpperCase()}
                    </div>
                    <div className="flex-1">
                      <div className="font-medium">{planet.name}</div>
                      {planet.description && (
                        <div className="text-sm text-muted-foreground">{planet.description}</div>
                      )}
                    </div>
                    {selectedTargetPlanet?.id === planet.id && (
                      <CheckCircle2 className="w-5 h-5 text-primary" />
                    )}
                  </div>
                </button>
              ))}
            {planets.filter(p => p.id !== currentPlanet?.id).length === 0 && (
              <div className="text-center py-8 text-muted-foreground">
                No other planets available
              </div>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              setShowMoveToDialog(false)
              setSelectedTargetPlanet(null)
            }}
            disabled={isMoving}
          >
            Cancel
          </Button>
          <Button
            onClick={handleMoveToConfirm}
            disabled={!selectedTargetPlanet || isMoving}
          >
            {isMoving ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Moving...
              </>
            ) : (
              "Move"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    </>
  )
}

