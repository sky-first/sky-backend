"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Star, Sparkles, Folder, Search } from "lucide-react"
import { useStarredStore } from "@/store/starred-store"
import { usePlanetStore } from "@/store/planet-store"
import { useSpaceStore } from "@/store/space-store"
import { useRouter } from "next/navigation"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { colorNameToHex } from "@/lib/utils/planet-colors"

interface StarredDropdownProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onClose?: () => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
}

export function StarredDropdown({ isOpen, onOpenChange, onClose, onMouseEnter, onMouseLeave }: StarredDropdownProps) {
  const router = useRouter()
  const { getStarredPlanets, getStarredSpaces, toggleStar } = useStarredStore()
  const { switchPlanet } = usePlanetStore()
  const { setCurrentSpace } = useSpaceStore()
  const [searchQuery, setSearchQuery] = useState("")

  const starredPlanets = getStarredPlanets()
  const starredSpaces = getStarredSpaces()
  
  const allStarred = [
    ...starredPlanets.map(item => ({ ...item, type: 'planet' as const })),
    ...starredSpaces.map(item => ({ ...item, type: 'space' as const }))
  ]

  const filteredStarred = allStarred.filter(item =>
    item.name.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map(n => n[0])
      .join('')
      .slice(0, 2)
      .toUpperCase()
  }

  const getAvatarColor = (name: string, color?: string) => {
    if (color) {
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
              Starred
            </h2>
            
            {/* Search Bar */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <Input
                type="text"
                placeholder="Filter starred items"
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
            {/* STARRED Section */}
            <div>
              <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3 px-2">
                STARRED ITEMS
              </div>
              
              {filteredStarred.length === 0 ? (
                <div className="px-2 py-8 text-center text-sm text-gray-500 dark:text-gray-400">
                  No starred items
                </div>
              ) : (
                <div className="space-y-1">
                  {filteredStarred.map((item) => {
                    const initials = item.icon || getInitials(item.name)
                    const avatarColor = getAvatarColor(item.name, item.color)
                    
                    return (
                      <button
                        key={`${item.type}-${item.id}`}
                        onClick={() => {
                          if (item.type === 'planet') {
                            handlePlanetClick(item.id)
                          } else {
                            handleSpaceClick(item.id)
                          }
                        }}
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
                        <button
                          onClick={(e) => handleUnstar(e, item.id, item.type, item)}
                          className="p-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity text-yellow-500"
                        >
                          <Star className="w-4 h-4 fill-yellow-500 text-yellow-500" />
                        </button>
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

