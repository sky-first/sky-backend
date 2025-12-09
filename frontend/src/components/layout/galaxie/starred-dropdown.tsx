"use client"

import { motion, AnimatePresence } from "framer-motion"
import { Star, Sparkles, Folder } from "lucide-react"
import { useStarredStore } from "@/store/starred-store"
import { usePlanetStore } from "@/store/planet-store"
import { useSpaceStore } from "@/store/space-store"
import { useRouter } from "next/navigation"
import { cn } from "@/lib/utils"
import { colorNameToHex } from "@/lib/utils/planet-colors"

interface StarredDropdownProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onClose?: () => void
}

export function StarredDropdown({ isOpen, onOpenChange, onClose }: StarredDropdownProps) {
  const router = useRouter()
  const { getStarredPlanets, getStarredSpaces, toggleStar } = useStarredStore()
  const { switchPlanet } = usePlanetStore()
  const { setCurrentSpace } = useSpaceStore()

  const starredPlanets = getStarredPlanets()
  const starredSpaces = getStarredSpaces()

  const handlePlanetClick = async (planetId: string) => {
    try {
      await switchPlanet(planetId)
      onOpenChange(false)
      onClose?.()
      router.push("/dashboard")
    } catch (error) {
      console.error('Error switching planet:', error)
    }
  }

  const handleSpaceClick = (spaceId: string) => {
    onOpenChange(false)
    onClose?.()
  }

  const handleUnstar = (e: React.MouseEvent, id: string, type: 'planet' | 'space', item: any) => {
    e.stopPropagation()
    toggleStar({
      id,
      type,
      name: item.name,
      description: item.description,
      icon: item.icon,
      color: item.color,
    })
  }

  if (!isOpen) return null

  const hasItems = starredPlanets.length > 0 || starredSpaces.length > 0

  return (
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
            {starredPlanets.map((item) => {
              return (
                <div key={`planet-${item.id}`} className="flex items-center gap-2">
                  <button
                    onClick={() => handlePlanetClick(item.id)}
                    className={cn(
                      "flex-1 text-left px-3 py-2 rounded-lg",
                      "hover:bg-gray-100 dark:hover:bg-gray-800",
                      "transition-all duration-200"
                    )}
                  >
                    <span className="text-sm text-gray-700 dark:text-gray-300">{item.name}</span>
                  </button>
                  <button
                    onClick={(e) => handleUnstar(e, item.id, 'planet', item)}
                    className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700"
                  >
                    <Star className="w-3 h-3 fill-yellow-500 text-yellow-500" />
                  </button>
                </div>
              )
            })}

            {starredSpaces.map((item) => {
              return (
                <div key={`space-${item.id}`} className="flex items-center gap-2">
                  <button
                    onClick={() => handleSpaceClick(item.id)}
                    className={cn(
                      "flex-1 text-left px-3 py-2 rounded-lg",
                      "hover:bg-gray-100 dark:hover:bg-gray-800",
                      "transition-all duration-200"
                    )}
                  >
                    <span className="text-sm text-gray-700 dark:text-gray-300">{item.name}</span>
                  </button>
                  <button
                    onClick={(e) => handleUnstar(e, item.id, 'space', item)}
                    className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700"
                  >
                    <Star className="w-3 h-3 fill-yellow-500 text-yellow-500" />
                  </button>
                </div>
              )
            })}

            {!hasItems && (
              <div className="px-3 py-4 text-center text-sm text-gray-500 dark:text-gray-400">
                No starred items
              </div>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

