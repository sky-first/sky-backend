"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Clock, Sparkles, Folder, Search } from "lucide-react"
import { useRecentsStore } from "@/store/recents-store"
import { usePlanetStore } from "@/store/planet-store"
import { useSpaceStore } from "@/store/space-store"
import { useRouter } from "next/navigation"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { colorNameToHex } from "@/lib/utils/planet-colors"

interface RecentsDropdownProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onClose?: () => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
}

export function RecentsDropdown({ isOpen, onOpenChange, onClose, onMouseEnter, onMouseLeave }: RecentsDropdownProps) {
  const router = useRouter()
  const { getRecentPlanets, getRecentSpaces } = useRecentsStore()
  const { switchPlanet } = usePlanetStore()
  const { spaces, setCurrentSpace } = useSpaceStore()
  const [searchQuery, setSearchQuery] = useState("")

  const recentPlanets = getRecentPlanets()
  const recentSpaces = getRecentSpaces()
  
  const allRecents = [
    ...recentPlanets.map(item => ({ ...item, type: 'planet' as const })),
    ...recentSpaces.map(item => ({ ...item, type: 'space' as const }))
  ].sort((a, b) => {
    // Sort by most recent (you can add timestamp if available)
    return 0
  })

  const filteredRecents = allRecents.filter(item =>
    item.name.toLowerCase().includes(searchQuery.toLowerCase())
  )

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
    const space = spaces.find(s => s.id === spaceId)
    if (space) {
      setCurrentSpace(space)
    }
    onOpenChange(false)
    onClose?.()
  }

  const handleItemClick = (item: typeof allRecents[0]) => {
    if (item.type === 'planet') {
      handlePlanetClick(item.id)
    } else {
      handleSpaceClick(item.id)
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

  const getAvatarColor = (name: string) => {
    const colors = [
      'bg-blue-500',
      'bg-green-500',
      'bg-purple-500',
      'bg-pink-500',
      'bg-orange-500',
      'bg-teal-500',
      'bg-red-500',
      'bg-indigo-500'
    ]
    const index = name.charCodeAt(0) % colors.length
    return colors[index]
  }

  if (!isOpen) return null

  return (
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
          onMouseEnter={onMouseEnter}
          onMouseLeave={onMouseLeave}
        >
          {/* Header */}
          <div className="p-5 border-b border-gray-200 dark:border-gray-800">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
              Recent
            </h2>
            
            {/* Search Bar */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <Input
                type="text"
                placeholder="Filter recent items"
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
            {/* RECENTLY VIEWED Section */}
            <div>
              <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3 px-2">
                RECENTLY VIEWED
              </div>
              
              {filteredRecents.length === 0 ? (
                <div className="px-2 py-8 text-center text-sm text-gray-500 dark:text-gray-400">
                  No recent items
                </div>
              ) : (
                <div className="space-y-1">
                  {filteredRecents.map((item) => {
                    const initials = getInitials(item.name)
                    const avatarColor = getAvatarColor(item.name)
                    
                    return (
                      <button
                        key={`${item.type}-${item.id}`}
                        onClick={() => handleItemClick(item)}
                        className={cn(
                          "w-full text-left px-3 py-2.5 rounded-lg",
                          "transition-all duration-200",
                          "hover:bg-gray-50 dark:hover:bg-gray-800",
                          "flex items-center gap-3 group"
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
                            {item.name}
                          </div>
                        </div>
                        <Clock className="w-4 h-4 text-gray-400 shrink-0" />
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

