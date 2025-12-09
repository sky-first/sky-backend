"use client"

import { motion, AnimatePresence } from "framer-motion"
import { Clock, Sparkles, Folder } from "lucide-react"
import { useRecentsStore } from "@/store/recents-store"
import { usePlanetStore } from "@/store/planet-store"
import { useSpaceStore } from "@/store/space-store"
import { useRouter } from "next/navigation"
import { cn } from "@/lib/utils"
import { colorNameToHex } from "@/lib/utils/planet-colors"

interface RecentsDropdownProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onClose?: () => void
}

export function RecentsDropdown({ isOpen, onOpenChange, onClose }: RecentsDropdownProps) {
  const router = useRouter()
  const { getRecentPlanets, getRecentSpaces } = useRecentsStore()
  const { switchPlanet } = usePlanetStore()
  const { setCurrentSpace } = useSpaceStore()

  const recentPlanets = getRecentPlanets().slice(0, 5)
  const recentSpaces = getRecentSpaces().slice(0, 5)

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

  if (!isOpen) return null

  const hasItems = recentPlanets.length > 0 || recentSpaces.length > 0

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
            {recentPlanets.map((item) => {
              const planetColor = item.color ? colorNameToHex(item.color) : '#6366f1'
              return (
                <button
                  key={`planet-${item.id}`}
                  onClick={() => handlePlanetClick(item.id)}
                  className={cn(
                    "w-full text-left px-3 py-2 rounded-lg",
                    "hover:bg-gray-100 dark:hover:bg-gray-800",
                    "transition-all duration-200"
                  )}
                >
                  <span className="text-sm text-gray-700 dark:text-gray-300">{item.name}</span>
                </button>
              )
            })}

            {recentSpaces.map((item) => {
              return (
                <button
                  key={`space-${item.id}`}
                  onClick={() => handleSpaceClick(item.id)}
                  className={cn(
                    "w-full text-left px-3 py-2 rounded-lg",
                    "hover:bg-gray-100 dark:hover:bg-gray-800",
                    "transition-all duration-200"
                  )}
                >
                  <span className="text-sm text-gray-700 dark:text-gray-300">{item.name}</span>
                </button>
              )
            })}

            {!hasItems && (
              <div className="px-3 py-4 text-center text-sm text-gray-500 dark:text-gray-400">
                No recent items
              </div>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

