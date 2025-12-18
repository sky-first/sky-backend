"use client"

import { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Folder, Search, Plus, ChevronRight, MoreVertical, Edit2, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useSpaceStore, type Space } from "@/store/space-store"
import { useRecentsStore } from "@/store/recents-store"
import { useStarredStore } from "@/store/starred-store"
import { useRouter } from "next/navigation"
import { cn } from "@/lib/utils"
import { Star, Loader2 } from "lucide-react"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"

interface SpacesDropdownProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onClose?: () => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
  onCloseSidebar?: () => void
}

export function SpacesDropdown({ isOpen, onOpenChange, onClose, onMouseEnter, onMouseLeave, onCloseSidebar }: SpacesDropdownProps) {
  const router = useRouter()
  const { spaces, currentSpace, fetchSpaces, setCurrentSpace, isLoading, createSpace, updateSpace, deleteSpace } = useSpaceStore()
  const { addRecent } = useRecentsStore()
  const { toggleStar, isStarred } = useStarredStore()
  const [searchQuery, setSearchQuery] = useState("")
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [editingSpace, setEditingSpace] = useState<Space | null>(null)
  const [deletingSpace, setDeletingSpace] = useState<Space | null>(null)
  const [editName, setEditName] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showSpaceActions, setShowSpaceActions] = useState<Space | null>(null)
  const timeoutRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    if (isOpen && spaces.length === 0) {
      fetchSpaces().catch(console.error)
    }
  }, [isOpen, spaces.length, fetchSpaces])

  // Cancel timeout when any dialog opens and prevent dropdown from closing
  useEffect(() => {
    if (showCreateDialog || editingSpace || deletingSpace) {
      // Cancel any pending timeout to keep dropdown open
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }
    }
  }, [showCreateDialog, editingSpace, deletingSpace])

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
    }
  }, [])

  const filteredSpaces = spaces.filter((space) =>
    space.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    space.description?.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const handleSpaceClick = (space: Space) => {
    setCurrentSpace(space)
    addRecent({
      id: space.id,
      type: 'space',
      name: space.name,
      description: space.description,
    })
    onOpenChange(false)
    onClose?.()
  }

  const handleStarClick = (e: React.MouseEvent, space: Space) => {
    e.stopPropagation()
    toggleStar({
      id: space.id,
      type: 'space',
      name: space.name,
      description: space.description,
    })
  }

  const handleViewAll = () => {
    onOpenChange(false)
    onClose?.()
    router.push("/dashboard/settings?tab=spaces")
  }

  const handleMenuClick = (space: Space, e: React.MouseEvent) => {
    e.stopPropagation()
    setShowSpaceActions(space)
  }

  const handleRenameClick = () => {
    if (!showSpaceActions) return
    setEditingSpace(showSpaceActions)
    setEditName(showSpaceActions.name)
    setShowSpaceActions(null)
  }

  const handleRenameSubmit = async () => {
    if (!editingSpace || !editName.trim()) return
    
    setIsSubmitting(true)
    try {
      await updateSpace(editingSpace.id, { name: editName.trim() })
      await fetchSpaces()
      setEditingSpace(null)
      setEditName("")
      // Close dropdown after successful rename
      onOpenChange(false)
      onClose?.()
    } catch (error) {
      console.error('Error renaming space:', error)
      alert('Erro ao renomear space. Por favor, tente novamente.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDeleteClick = () => {
    if (!showSpaceActions) return
    setDeletingSpace(showSpaceActions)
    setShowSpaceActions(null)
  }

  const handleDeleteConfirm = async () => {
    if (!deletingSpace) return
    
    setIsSubmitting(true)
    try {
      await deleteSpace(deletingSpace.id)
      await fetchSpaces()
      setDeletingSpace(null)
      // Close dropdown after successful delete
      onOpenChange(false)
      onClose?.()
    } catch (error) {
      console.error('Error deleting space:', error)
      alert('Erro ao deletar space. Por favor, tente novamente.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const [spaceFormData, setSpaceFormData] = useState({
    name: "",
    description: "",
  })
  const [spaceError, setSpaceError] = useState<string | null>(null)

  const handleCreateSpaceSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSpaceError(null)

    if (!spaceFormData.name.trim()) {
      setSpaceError("Name is required")
      return
    }

    try {
      await createSpace({
        name: spaceFormData.name.trim(),
        description: spaceFormData.description.trim() || undefined,
      })
      setShowCreateDialog(false)
      setSpaceFormData({ name: "", description: "" })
    } catch (error) {
      console.error("Error creating space:", error)
      setSpaceError(error instanceof Error ? error.message : "Failed to create space")
    }
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
            // Don't close dropdown if any dialog is open
            if (showCreateDialog || editingSpace || deletingSpace) {
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
              Spaces
            </h2>
            
            {/* Search Bar */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <Input
                type="text"
                placeholder="Filter spaces..."
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
            {/* SPACES Section */}
            <div className="mb-6">
              <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3 px-2">
                SPACES
              </div>
              <div className="space-y-1">
                {isLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
                  </div>
                ) : filteredSpaces.length === 0 ? (
                  <div className="px-2 py-4 text-center text-sm text-gray-500 dark:text-gray-400">
                    No spaces found
                  </div>
                ) : (
                  filteredSpaces.map((space) => {
                    const starred = isStarred(space.id, 'space')
                    
                    return (
                      <div key={space.id} className="group relative">
                        <div
                          onClick={() => handleSpaceClick(space)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              handleSpaceClick(space)
                            }
                          }}
                          className={cn(
                            "w-full text-left px-3 py-2.5 rounded-lg",
                            "transition-all duration-200",
                            "hover:bg-gray-50 dark:hover:bg-gray-800",
                            "flex items-center gap-3",
                            "cursor-pointer",
                            currentSpace?.id === space.id && "bg-blue-50 dark:bg-blue-900/20"
                          )}
                        >
                          <div className={cn(
                            "w-8 h-8 rounded-full flex items-center justify-center",
                            "text-white text-xs font-semibold",
                                                    "bg-blue-500" // Default color since Space API doesn't have color field
                          )}>
                            {space.name.charAt(0).toUpperCase()}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium text-gray-900 dark:text-white truncate">
                              {space.name}
                            </div>
                            {space.description && (
                              <div className="text-xs text-gray-500 dark:text-gray-400 truncate">
                                {space.description}
                              </div>
                            )}
                          </div>
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              onClick={(e) => handleStarClick(e, space)}
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
                              onClick={(e) => handleMenuClick(space, e)}
                              className={cn(
                                "p-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity",
                                "text-gray-400 hover:text-gray-600 dark:hover:text-gray-300",
                                showSpaceActions?.id === space.id && "opacity-100"
                              )}
                            >
                              <MoreVertical className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                        
                        {/* Space Actions Sidetip */}
                        <AnimatePresence>
                          {showSpaceActions?.id === space.id && (
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
                                  setShowSpaceActions(null)
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

            {/* Actions */}
            <div className="space-y-1 pt-4 border-t border-gray-200 dark:border-gray-800">
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
                New Space
              </button>
              
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
                View all spaces
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
    
    {/* Create Space Dialog */}
    <Dialog 
      open={showCreateDialog} 
      onOpenChange={(open) => {
        setShowCreateDialog(open)
        // When dialog closes, cancel any pending timeout
        if (!open && timeoutRef.current) {
          clearTimeout(timeoutRef.current)
          timeoutRef.current = null
        }
      }}
    >
      <DialogContent 
        className="max-w-md"
        onInteractOutside={(e) => {
          // Check if the click is actually outside the dialog content
          const target = e.target as HTMLElement
          const dialogContent = target.closest('[data-slot="dialog-content"]')
          
          // If clicking inside the dialog content, prevent closing
          if (dialogContent) {
            e.preventDefault()
          }
          // Otherwise, allow normal behavior (closing when clicking outside)
        }}
        onPointerDownOutside={(e) => {
          // Check if the click is actually outside the dialog content
          const target = e.target as HTMLElement
          const dialogContent = target.closest('[data-slot="dialog-content"]')
          
          // If clicking inside the dialog content, prevent closing
          if (dialogContent) {
            e.preventDefault()
          }
          // Otherwise, allow normal behavior (closing when clicking outside)
        }}
        onClick={(e) => {
          // Stop propagation to prevent any parent handlers from closing the dialog
          // when clicking inside the dialog content
          e.stopPropagation()
        }}
        onMouseDown={(e) => {
          // Stop propagation on mouse down as well
          e.stopPropagation()
        }}
      >
        <DialogHeader
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <DialogTitle className="flex items-center gap-2">
            <Folder className="w-5 h-5 text-blue-500" />
            Create New Space
          </DialogTitle>
          <DialogDescription>
            Create a new workspace area for your organization
          </DialogDescription>
        </DialogHeader>

        <form 
          onSubmit={handleCreateSpaceSubmit} 
          className="space-y-4"
          onClick={(e) => {
            // Stop propagation to prevent closing dialog when clicking inside form
            e.stopPropagation()
          }}
        >
          <div 
            className="space-y-2"
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <label htmlFor="space-name" className="text-sm font-medium">
              Name <span className="text-red-500">*</span>
            </label>
            <Input
              id="space-name"
              value={spaceFormData.name}
              onChange={(e) => setSpaceFormData({ ...spaceFormData, name: e.target.value })}
              onClick={(e) => e.stopPropagation()}
              onMouseDown={(e) => e.stopPropagation()}
              placeholder="Ex: Marketing System"
              maxLength={255}
              required
              disabled={isLoading}
              className={spaceError && !spaceFormData.name.trim() ? "border-red-500" : ""}
            />
          </div>

          <div 
            className="space-y-2"
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <label htmlFor="space-description" className="text-sm font-medium">
              Description <span className="text-gray-400 text-xs">(optional)</span>
            </label>
            <Textarea
              id="space-description"
              value={spaceFormData.description}
              onChange={(e) => setSpaceFormData({ ...spaceFormData, description: e.target.value })}
              onClick={(e) => e.stopPropagation()}
              onMouseDown={(e) => e.stopPropagation()}
              placeholder="Describe the purpose of this space..."
              rows={3}
              disabled={isLoading}
            />
          </div>

          {spaceError && (
            <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
              <p className="text-sm text-red-600 dark:text-red-400">{spaceError}</p>
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={(e) => {
                e.stopPropagation()
                setShowCreateDialog(false)
                setSpaceFormData({ name: "", description: "" })
                setSpaceError(null)
              }}
              disabled={isLoading}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              onClick={(e) => e.stopPropagation()}
              disabled={isLoading || !spaceFormData.name.trim()}
              className="gap-2"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <Folder className="w-4 h-4" />
                  Create Space
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>

    {/* Rename Space Dialog */}
    <Dialog open={!!editingSpace} onOpenChange={(open) => {
      if (!open) {
        setEditingSpace(null)
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
          <DialogTitle>Rename Space</DialogTitle>
          <DialogDescription>
            Enter a new name for this space.
          </DialogDescription>
        </DialogHeader>
        <div className="py-4">
          <Input
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            placeholder="Space name"
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
              setEditingSpace(null)
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

    {/* Delete Space Dialog */}
    <Dialog open={!!deletingSpace} onOpenChange={(open) => {
      if (!open) {
        setDeletingSpace(null)
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
          <DialogTitle>Delete Space</DialogTitle>
          <DialogDescription>
            Are you sure you want to delete "{deletingSpace?.name}"? This action cannot be undone and will delete all crews and data associated with this space.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => setDeletingSpace(null)}
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
    </>
  )
}

