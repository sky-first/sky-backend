"use client"

import { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Users, Search, Plus, ChevronRight, Star } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useCrewStore, type Crew } from "@/store/crew-store"
import { useRecentsStore } from "@/store/recents-store"
import { useStarredStore } from "@/store/starred-store"
import { useRouter } from "next/navigation"
import { cn } from "@/lib/utils"
import { Loader2 } from "lucide-react"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { useSpaceStore } from "@/store/space-store"

interface CrewsDropdownProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onClose?: () => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
}

export function CrewsDropdown({ isOpen, onOpenChange, onClose, onMouseEnter, onMouseLeave }: CrewsDropdownProps) {
  const router = useRouter()
  const { crews, currentCrew, fetchCrews, setCurrentCrew, isLoading, createCrew } = useCrewStore()
  const { currentSpace } = useSpaceStore()
  const { addRecent } = useRecentsStore()
  const { toggleStar, isStarred } = useStarredStore()
  const [searchQuery, setSearchQuery] = useState("")
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [newCrewName, setNewCrewName] = useState("")
  const [newCrewDescription, setNewCrewDescription] = useState("")
  const timeoutRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    if (isOpen && crews.length === 0) {
      fetchCrews({ space_id: currentSpace?.id }).catch(console.error)
    }
  }, [isOpen, crews.length, fetchCrews, currentSpace?.id])

  // Cancel timeout when dialog opens and prevent dropdown from closing
  useEffect(() => {
    if (showCreateDialog) {
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

  const filteredCrews = crews.filter(crew =>
    crew.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    crew.description?.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const handleCrewClick = async (crew: Crew) => {
    try {
      setCurrentCrew(crew)
      addRecent({
        id: crew.id,
        type: 'crew',
        name: crew.name,
        description: crew.description || undefined,
      })
      onOpenChange(false)
      onClose?.()
      // Navigate to crew details or settings
      router.push(`/dashboard/settings?tab=crews`)
    } catch (error) {
      console.error('Error selecting crew:', error)
    }
  }

  const handleStarClick = (e: React.MouseEvent, crew: Crew) => {
    e.stopPropagation()
    toggleStar({
      id: crew.id,
      type: 'crew',
      name: crew.name,
      description: crew.description || undefined,
    })
  }

  const handleCreateCrewSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newCrewName.trim() || !currentSpace) return

    try {
      await createCrew({
        name: newCrewName.trim(),
        description: newCrewDescription.trim() || undefined,
        space_id: currentSpace.id,
      })
      setNewCrewName("")
      setNewCrewDescription("")
      setShowCreateDialog(false)
    } catch (error) {
      console.error('Error creating crew:', error)
    }
  }

  const handleViewAll = () => {
    router.push("/dashboard/settings?tab=crews")
    onOpenChange(false)
    onClose?.()
  }

  if (!isOpen) return null

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -10 }}
      transition={{ duration: 0.2 }}
      className="w-80 flex flex-col bg-white dark:bg-gray-900 border-l border-gray-200 dark:border-gray-800"
      onMouseEnter={() => {
        if (timeoutRef.current) {
          clearTimeout(timeoutRef.current)
          timeoutRef.current = null
        }
        onMouseEnter?.()
      }}
      onMouseLeave={() => {
        if (showCreateDialog) {
          return
        }
        timeoutRef.current = setTimeout(() => {
          onOpenChange(false)
        }, 200)
        onMouseLeave?.()
      }}
    >
      {/* Header */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Crews</h2>
      </div>

      {/* Search */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-800">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
          <Input
            placeholder="Filter crews..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* Crews List */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-4">
          <div className="space-y-1">
            <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              CREWS
            </div>
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
              </div>
            ) : filteredCrews.length === 0 ? (
              <div className="text-sm text-gray-500 dark:text-gray-400 py-8 text-center">
                {searchQuery ? "No crews found" : "No crews yet"}
              </div>
            ) : (
              filteredCrews.map((crew) => {
                const initials = crew.name
                  .split(" ")
                  .map((n) => n[0])
                  .join("")
                  .toUpperCase()
                  .slice(0, 2)

                return (
                  <div
                    key={crew.id}
                    onClick={() => handleCrewClick(crew)}
                    className={cn(
                      "flex items-center gap-3 p-2 rounded-md cursor-pointer transition-colors",
                      "hover:bg-gray-100 dark:hover:bg-gray-800",
                      currentCrew?.id === crew.id && "bg-blue-50 dark:bg-blue-900/20"
                    )}
                  >
                    {/* Avatar */}
                    <div className="w-8 h-8 rounded-full bg-blue-500 dark:bg-blue-600 flex items-center justify-center text-white text-xs font-medium flex-shrink-0">
                      {initials}
                    </div>
                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                        {crew.name}
                      </div>
                      {crew.description && (
                        <div className="text-xs text-gray-500 dark:text-gray-400 truncate">
                          {crew.description}
                        </div>
                      )}
                    </div>
                    {/* Star */}
                    <button
                      onClick={(e) => handleStarClick(e, crew)}
                      className={cn(
                        "p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors",
                        "flex-shrink-0"
                      )}
                    >
                      <Star
                        className={cn(
                          "w-4 h-4",
                          isStarred(crew.id, 'crew')
                            ? "fill-yellow-400 text-yellow-400"
                            : "text-gray-400"
                        )}
                      />
                    </button>
                  </div>
                )
              })
            )}
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="p-4 border-t border-gray-200 dark:border-gray-800">
        <div className="space-y-1 pt-4 border-t border-gray-200 dark:border-gray-800">
          <button
            onClick={(e) => {
              e.stopPropagation()
              setShowCreateDialog(true)
            }}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-md transition-colors"
          >
            <Plus className="w-4 h-4" /> New Crew
          </button>
          <button
            onClick={handleViewAll}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-md transition-colors"
          >
            All Crews
          </button>
        </div>
      </div>

      {/* Create Crew Dialog */}
      <Dialog
        open={showCreateDialog}
        onOpenChange={(open) => {
          setShowCreateDialog(open)
          if (!open && timeoutRef.current) {
            clearTimeout(timeoutRef.current)
            timeoutRef.current = null
          }
        }}
      >
        <DialogContent
          onInteractOutside={(e) => {
            const target = e.target as HTMLElement
            const dialogContent = target.closest('[data-slot="dialog-content"]')
            if (dialogContent) {
              e.preventDefault()
            }
          }}
          onPointerDownOutside={(e) => {
            const target = e.target as HTMLElement
            const dialogContent = target.closest('[data-slot="dialog-content"]')
            if (dialogContent) {
              e.preventDefault()
            }
          }}
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <DialogHeader
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <DialogTitle>Create New Crew</DialogTitle>
            <DialogDescription>
              Create a new crew in the current space.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={handleCreateCrewSubmit}
            className="space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div
              className="space-y-2"
              onClick={(e) => e.stopPropagation()}
              onMouseDown={(e) => e.stopPropagation()}
            >
              <label className="text-sm font-medium">Name</label>
              <Input
                value={newCrewName}
                onChange={(e) => setNewCrewName(e.target.value)}
                placeholder="Crew name"
                required
                onClick={(e) => e.stopPropagation()}
                onMouseDown={(e) => e.stopPropagation()}
              />
            </div>
            <div
              className="space-y-2"
              onClick={(e) => e.stopPropagation()}
              onMouseDown={(e) => e.stopPropagation()}
            >
              <label className="text-sm font-medium">Description</label>
              <Textarea
                value={newCrewDescription}
                onChange={(e) => setNewCrewDescription(e.target.value)}
                placeholder="Crew description (optional)"
                rows={3}
                onClick={(e) => e.stopPropagation()}
                onMouseDown={(e) => e.stopPropagation()}
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={(e) => {
                  e.stopPropagation()
                  setShowCreateDialog(false)
                }}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                onClick={(e) => e.stopPropagation()}
                disabled={!newCrewName.trim() || !currentSpace}
              >
                Create Crew
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </motion.div>
  )
}
