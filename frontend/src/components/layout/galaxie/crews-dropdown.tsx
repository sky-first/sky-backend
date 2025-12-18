"use client"

import { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Users, Search, Plus, ChevronRight, Star, MoreVertical, Edit2, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useCrewStore } from "@/store/crew-store"
import { type Crew } from "@/lib/api/crews"
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
  onCloseSidebar?: () => void
}

export function CrewsDropdown({ isOpen, onOpenChange, onClose, onMouseEnter, onMouseLeave, onCloseSidebar }: CrewsDropdownProps) {
  const router = useRouter()
  const { crews, currentCrew, fetchCrews, setCurrentCrew, isLoading, createCrew, updateCrew, deleteCrew } = useCrewStore()
  const { currentSpace } = useSpaceStore()
  const { addRecent } = useRecentsStore()
  const { toggleStar, isStarred } = useStarredStore()
  const [searchQuery, setSearchQuery] = useState("")
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [newCrewName, setNewCrewName] = useState("")
  const [newCrewDescription, setNewCrewDescription] = useState("")
  const [editingCrew, setEditingCrew] = useState<Crew | null>(null)
  const [deletingCrew, setDeletingCrew] = useState<Crew | null>(null)
  const [editName, setEditName] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showCrewActions, setShowCrewActions] = useState<Crew | null>(null)
  const timeoutRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    if (isOpen && crews.length === 0) {
      fetchCrews({ space_id: currentSpace?.id }).catch(console.error)
    }
  }, [isOpen, crews.length, fetchCrews, currentSpace?.id])

  // Cancel timeout when any dialog opens and prevent dropdown from closing
  useEffect(() => {
    if (showCreateDialog || editingCrew || deletingCrew) {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }
    }
  }, [showCreateDialog, editingCrew, deletingCrew])

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

  const handleMenuClick = (crew: Crew, e: React.MouseEvent) => {
    e.stopPropagation()
    setShowCrewActions(crew)
  }

  const handleRenameClick = () => {
    if (!showCrewActions) return
    setEditingCrew(showCrewActions)
    setEditName(showCrewActions.name)
    setShowCrewActions(null)
  }

  const handleRenameSubmit = async () => {
    if (!editingCrew || !editName.trim()) return
    
    setIsSubmitting(true)
    try {
      await updateCrew(editingCrew.id, { name: editName.trim() })
      await fetchCrews({ space_id: currentSpace?.id })
      setEditingCrew(null)
      setEditName("")
      // Close dropdown after successful rename
      onOpenChange(false)
      onClose?.()
    } catch (error) {
      console.error('Error renaming crew:', error)
      alert('Erro ao renomear crew. Por favor, tente novamente.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDeleteClick = () => {
    if (!showCrewActions) return
    setDeletingCrew(showCrewActions)
    setShowCrewActions(null)
  }

  const handleDeleteConfirm = async () => {
    if (!deletingCrew) return
    
    setIsSubmitting(true)
    try {
      await deleteCrew(deletingCrew.id)
      await fetchCrews({ space_id: currentSpace?.id })
      setDeletingCrew(null)
      // Close dropdown after successful delete
      onOpenChange(false)
      onClose?.()
    } catch (error) {
      console.error('Error deleting crew:', error)
      alert('Erro ao deletar crew. Por favor, tente novamente.')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!isOpen) return null

  return (
    <>
    <AnimatePresence>
    {isOpen && (
    <motion.div
      key="crews-dropdown"
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
        // Don't close dropdown if any dialog is open
        if (showCreateDialog || editingCrew || deletingCrew) {
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
                  <div key={crew.id} className="group relative">
                    <div
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
                      {/* Star and Menu */}
                      <div className="flex items-center gap-1">
                        <button
                          onClick={(e) => handleStarClick(e, crew)}
                          className={cn(
                            "p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors",
                            "flex-shrink-0 opacity-0 group-hover:opacity-100",
                            isStarred(crew.id, 'crew') && "opacity-100"
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
                        <button
                          type="button"
                          onClick={(e) => handleMenuClick(crew, e)}
                          className={cn(
                            "p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity",
                            "text-gray-400 hover:text-gray-600 dark:hover:text-gray-300",
                            showCrewActions?.id === crew.id && "opacity-100"
                          )}
                        >
                          <MoreVertical className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                    
                    {/* Crew Actions Sidetip */}
                    <AnimatePresence>
                      {showCrewActions?.id === crew.id && (
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
                            if (timeoutRef.current) {
                              clearTimeout(timeoutRef.current)
                              timeoutRef.current = null
                            }
                          }}
                          onMouseLeave={() => {
                            setTimeout(() => {
                              setShowCrewActions(null)
                            }, 150)
                          }}
                        >
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
      </div>

      {/* Actions */}
      <div className="p-4 border-t border-gray-200 dark:border-gray-800">
        <div className="space-y-1 pt-4 border-t border-gray-200 dark:border-gray-800">
          <button
            onClick={(e) => {
              e.stopPropagation()
              setShowCreateDialog(true)
              // Don't close sidebar immediately - let it stay open while dialog is open
              // The sidebar will close automatically when mouse leaves if no dialog is open
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

      {/* Rename Crew Dialog */}
      <Dialog open={!!editingCrew} onOpenChange={(open) => {
        if (!open) {
          setEditingCrew(null)
          setEditName("")
          // Close dropdown when dialog closes
          onOpenChange(false)
          onClose?.()
        }
      }}>
        <DialogContent
          onInteractOutside={(e) => {
            // Prevent closing when clicking outside if dropdown is still open
            e.preventDefault()
          }}
          onPointerDownOutside={(e) => {
            // Prevent closing when clicking outside if dropdown is still open
            e.preventDefault()
          }}
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <DialogHeader>
            <DialogTitle>Rename Crew</DialogTitle>
            <DialogDescription>
              Enter a new name for this crew.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Input
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              placeholder="Crew name"
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
                setEditingCrew(null)
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

      {/* Delete Crew Dialog */}
      <Dialog open={!!deletingCrew} onOpenChange={(open) => {
        if (!open) {
          setDeletingCrew(null)
          // Close dropdown when dialog closes
          onOpenChange(false)
          onClose?.()
        }
      }}>
        <DialogContent
          onInteractOutside={(e) => {
            // Prevent closing when clicking outside if dropdown is still open
            e.preventDefault()
          }}
          onPointerDownOutside={(e) => {
            // Prevent closing when clicking outside if dropdown is still open
            e.preventDefault()
          }}
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <DialogHeader>
            <DialogTitle>Delete Crew</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete "{deletingCrew?.name}"? This action cannot be undone and will delete all members and data associated with this crew.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeletingCrew(null)}
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
    </motion.div>
    )}
    </AnimatePresence>
    </>
  )
}
