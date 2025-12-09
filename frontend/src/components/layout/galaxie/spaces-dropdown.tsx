"use client"

import { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Folder, Search, Plus, ChevronRight } from "lucide-react"
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
}

export function SpacesDropdown({ isOpen, onOpenChange, onClose }: SpacesDropdownProps) {
  const router = useRouter()
  const { spaces, currentSpace, fetchSpaces, setCurrentSpace, isLoading, createSpace } = useSpaceStore()
  const { addRecent } = useRecentsStore()
  const { toggleStar, isStarred } = useStarredStore()
  const [searchQuery, setSearchQuery] = useState("")
  const [showCreateDialog, setShowCreateDialog] = useState(false)

  useEffect(() => {
    if (isOpen && spaces.length === 0) {
      fetchSpaces().catch(console.error)
    }
  }, [isOpen, spaces.length, fetchSpaces])

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
      icon: space.icon,
      color: space.color,
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
      icon: space.icon,
      color: space.color,
    })
  }

  const handleViewAll = () => {
    onOpenChange(false)
    onClose?.()
    router.push("/dashboard/settings?tab=spaces")
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
            {filteredSpaces.slice(0, 5).map((space) => {
              const starred = isStarred(space.id, 'space')
              
              return (
                <button
                  key={space.id}
                  onClick={() => handleSpaceClick(space)}
                  className={cn(
                    "w-full text-left px-3 py-2 rounded-lg",
                    "transition-all duration-200",
                    "hover:bg-gray-100 dark:hover:bg-gray-800",
                    "text-gray-700 dark:text-gray-300"
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm flex-1">{space.name}</span>
                    <button
                      onClick={(e) => handleStarClick(e, space)}
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
              )
            })}
            
            {/* New Space */}
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
                <span className="text-sm">New Space</span>
              </div>
            </button>
            
            {/* All Spaces */}
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
              All Spaces
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
    
    {/* Create Space Dialog */}
    <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Folder className="w-5 h-5 text-blue-500" />
            Create New Space
          </DialogTitle>
          <DialogDescription>
            Create a new workspace area for your organization
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleCreateSpaceSubmit} className="space-y-4">
          <div className="space-y-2">
            <label htmlFor="space-name" className="text-sm font-medium">
              Name <span className="text-red-500">*</span>
            </label>
            <Input
              id="space-name"
              value={spaceFormData.name}
              onChange={(e) => setSpaceFormData({ ...spaceFormData, name: e.target.value })}
              placeholder="Ex: Marketing System"
              maxLength={255}
              required
              disabled={isLoading}
              className={spaceError && !spaceFormData.name.trim() ? "border-red-500" : ""}
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="space-description" className="text-sm font-medium">
              Description <span className="text-gray-400 text-xs">(optional)</span>
            </label>
            <Textarea
              id="space-description"
              value={spaceFormData.description}
              onChange={(e) => setSpaceFormData({ ...spaceFormData, description: e.target.value })}
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
              onClick={() => {
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
    </>
  )
}

