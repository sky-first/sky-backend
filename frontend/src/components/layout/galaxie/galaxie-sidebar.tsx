"use client"

import { useState, useEffect, useRef } from "react"
import { useRouter } from "next/navigation"
import { motion, AnimatePresence } from "framer-motion"
import {
  Folder,
  Sparkles,
  Clock,
  Star,
  Radio,
  User,
  LogOut,
  X,
  ChevronRight,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { useSidebarStore } from "@/store/sidebar-store"
import { useUserStore } from "@/store/user-store"
import { usePlanetStore } from "@/store/planet-store"
import { useStarredStore } from "@/store/starred-store"
import { cn } from "@/lib/utils"
import { SpacesDropdown } from "./spaces-dropdown"
import { PlanetsDropdown } from "./planets-dropdown"
import { RecentsDropdown } from "./recents-dropdown"
import { StarredDropdown } from "./starred-dropdown"
import { SignalsDropdown } from "./signals-dropdown"
import { ProfileDropdown } from "./profile-dropdown"
import { CreatePlanetDialog } from "@/components/workspaces/create-workspace-dialog"
import { dashboardsApi } from "@/lib/api/dashboards"

export function GalaxieSidebar() {
  const router = useRouter()
  const { isOpen, setIsOpen } = useSidebarStore()
  const { user } = useUserStore()
  const { currentPlanet } = usePlanetStore()
  const { toggleStar, isStarred } = useStarredStore()
  
  const [showCreatePlanetDialog, setShowCreatePlanetDialog] = useState(false)
  
  // Dropdown states
  const [showSpacesDropdown, setShowSpacesDropdown] = useState(false)
  const [showPlanetsDropdown, setShowPlanetsDropdown] = useState(false)
  const [showRecentsDropdown, setShowRecentsDropdown] = useState(false)
  const [showStarredDropdown, setShowStarredDropdown] = useState(false)
  const [showSignalsDropdown, setShowSignalsDropdown] = useState(false)
  const [showProfileDropdown, setShowProfileDropdown] = useState(false)
  
  // Timeout refs for hover behavior
  const spacesTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const planetsTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const recentsTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const starredTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const signalsTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const profileTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  
  // Close on escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        setIsOpen(false)
      }
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [isOpen, setIsOpen])
  
  // Close all dropdowns when sidebar closes
  useEffect(() => {
    if (!isOpen) {
      setShowSpacesDropdown(false)
      setShowPlanetsDropdown(false)
      setShowRecentsDropdown(false)
      setShowStarredDropdown(false)
      setShowSignalsDropdown(false)
      setShowProfileDropdown(false)
    }
  }, [isOpen])
  
  const closeAllDropdowns = () => {
    setShowSpacesDropdown(false)
    setShowPlanetsDropdown(false)
    setShowRecentsDropdown(false)
    setShowStarredDropdown(false)
    setShowSignalsDropdown(false)
    setShowProfileDropdown(false)
  }
  
  const handleStarPlanet = () => {
    if (!currentPlanet) return
    toggleStar({
      id: currentPlanet.id,
      type: 'planet',
      name: currentPlanet.name,
      description: currentPlanet.description,
      icon: currentPlanet.icon,
      color: currentPlanet.color,
    })
  }
  
  const navItems = [
    {
      icon: Radio,
      label: "Signals",
      onClick: () => {
        closeAllDropdowns()
        setShowSignalsDropdown(true)
      },
      onMouseEnter: () => {
        if (spacesTimeoutRef.current) {
          clearTimeout(spacesTimeoutRef.current)
          spacesTimeoutRef.current = null
        }
        if (planetsTimeoutRef.current) {
          clearTimeout(planetsTimeoutRef.current)
          planetsTimeoutRef.current = null
        }
        if (recentsTimeoutRef.current) {
          clearTimeout(recentsTimeoutRef.current)
          recentsTimeoutRef.current = null
        }
        if (starredTimeoutRef.current) {
          clearTimeout(starredTimeoutRef.current)
          starredTimeoutRef.current = null
        }
        if (profileTimeoutRef.current) {
          clearTimeout(profileTimeoutRef.current)
          profileTimeoutRef.current = null
        }
        setShowSpacesDropdown(false)
        setShowPlanetsDropdown(false)
        setShowRecentsDropdown(false)
        setShowStarredDropdown(false)
        setShowProfileDropdown(false)
        
        if (signalsTimeoutRef.current) {
          clearTimeout(signalsTimeoutRef.current)
          signalsTimeoutRef.current = null
        }
        setShowSignalsDropdown(true)
      },
      onMouseLeave: () => {
        signalsTimeoutRef.current = setTimeout(() => {
          setShowSignalsDropdown(false)
        }, 150)
      },
    },
    {
      icon: Clock,
      label: "Recent",
      onClick: () => {
        closeAllDropdowns()
        setShowRecentsDropdown(true)
      },
      onMouseEnter: () => {
        if (spacesTimeoutRef.current) {
          clearTimeout(spacesTimeoutRef.current)
          spacesTimeoutRef.current = null
        }
        if (planetsTimeoutRef.current) {
          clearTimeout(planetsTimeoutRef.current)
          planetsTimeoutRef.current = null
        }
        if (starredTimeoutRef.current) {
          clearTimeout(starredTimeoutRef.current)
          starredTimeoutRef.current = null
        }
        if (signalsTimeoutRef.current) {
          clearTimeout(signalsTimeoutRef.current)
          signalsTimeoutRef.current = null
        }
        if (profileTimeoutRef.current) {
          clearTimeout(profileTimeoutRef.current)
          profileTimeoutRef.current = null
        }
        setShowSpacesDropdown(false)
        setShowPlanetsDropdown(false)
        setShowStarredDropdown(false)
        setShowSignalsDropdown(false)
        setShowProfileDropdown(false)
        
        if (recentsTimeoutRef.current) {
          clearTimeout(recentsTimeoutRef.current)
          recentsTimeoutRef.current = null
        }
        setShowRecentsDropdown(true)
      },
      onMouseLeave: () => {
        recentsTimeoutRef.current = setTimeout(() => {
          setShowRecentsDropdown(false)
        }, 150)
      },
    },
    {
      icon: Star,
      label: "Starred",
      onClick: () => {
        closeAllDropdowns()
        setShowStarredDropdown(true)
      },
      onMouseEnter: () => {
        if (spacesTimeoutRef.current) {
          clearTimeout(spacesTimeoutRef.current)
          spacesTimeoutRef.current = null
        }
        if (planetsTimeoutRef.current) {
          clearTimeout(planetsTimeoutRef.current)
          planetsTimeoutRef.current = null
        }
        if (recentsTimeoutRef.current) {
          clearTimeout(recentsTimeoutRef.current)
          recentsTimeoutRef.current = null
        }
        if (signalsTimeoutRef.current) {
          clearTimeout(signalsTimeoutRef.current)
          signalsTimeoutRef.current = null
        }
        if (profileTimeoutRef.current) {
          clearTimeout(profileTimeoutRef.current)
          profileTimeoutRef.current = null
        }
        setShowSpacesDropdown(false)
        setShowPlanetsDropdown(false)
        setShowRecentsDropdown(false)
        setShowSignalsDropdown(false)
        setShowProfileDropdown(false)
        
        if (starredTimeoutRef.current) {
          clearTimeout(starredTimeoutRef.current)
          starredTimeoutRef.current = null
        }
        setShowStarredDropdown(true)
      },
      onMouseLeave: () => {
        starredTimeoutRef.current = setTimeout(() => {
          setShowStarredDropdown(false)
        }, 150)
      },
    },
    {
      icon: Folder,
      label: "Spaces",
      onClick: () => {
        closeAllDropdowns()
        setShowSpacesDropdown(true)
      },
      onMouseEnter: () => {
        if (planetsTimeoutRef.current) {
          clearTimeout(planetsTimeoutRef.current)
          planetsTimeoutRef.current = null
        }
        if (recentsTimeoutRef.current) {
          clearTimeout(recentsTimeoutRef.current)
          recentsTimeoutRef.current = null
        }
        if (starredTimeoutRef.current) {
          clearTimeout(starredTimeoutRef.current)
          starredTimeoutRef.current = null
        }
        if (signalsTimeoutRef.current) {
          clearTimeout(signalsTimeoutRef.current)
          signalsTimeoutRef.current = null
        }
        if (profileTimeoutRef.current) {
          clearTimeout(profileTimeoutRef.current)
          profileTimeoutRef.current = null
        }
        setShowPlanetsDropdown(false)
        setShowRecentsDropdown(false)
        setShowStarredDropdown(false)
        setShowSignalsDropdown(false)
        setShowProfileDropdown(false)
        
        if (spacesTimeoutRef.current) {
          clearTimeout(spacesTimeoutRef.current)
          spacesTimeoutRef.current = null
        }
        setShowSpacesDropdown(true)
      },
      onMouseLeave: () => {
        spacesTimeoutRef.current = setTimeout(() => {
          setShowSpacesDropdown(false)
        }, 150)
      },
    },
    {
      icon: Sparkles,
      label: "Planets",
      onClick: () => {
        closeAllDropdowns()
        setShowPlanetsDropdown(true)
      },
      onMouseEnter: () => {
        if (spacesTimeoutRef.current) {
          clearTimeout(spacesTimeoutRef.current)
          spacesTimeoutRef.current = null
        }
        if (recentsTimeoutRef.current) {
          clearTimeout(recentsTimeoutRef.current)
          recentsTimeoutRef.current = null
        }
        if (starredTimeoutRef.current) {
          clearTimeout(starredTimeoutRef.current)
          starredTimeoutRef.current = null
        }
        if (signalsTimeoutRef.current) {
          clearTimeout(signalsTimeoutRef.current)
          signalsTimeoutRef.current = null
        }
        if (profileTimeoutRef.current) {
          clearTimeout(profileTimeoutRef.current)
          profileTimeoutRef.current = null
        }
        setShowSpacesDropdown(false)
        setShowRecentsDropdown(false)
        setShowStarredDropdown(false)
        setShowSignalsDropdown(false)
        setShowProfileDropdown(false)
        
        if (planetsTimeoutRef.current) {
          clearTimeout(planetsTimeoutRef.current)
          planetsTimeoutRef.current = null
        }
        setShowPlanetsDropdown(true)
      },
      onMouseLeave: () => {
        planetsTimeoutRef.current = setTimeout(() => {
          setShowPlanetsDropdown(false)
        }, 150)
      },
    },
    {
      icon: Star,
      label: "Star this planet",
      onClick: () => {
        if (currentPlanet) {
          handleStarPlanet()
        }
      },
      isAction: true,
    },
    {
      icon: User,
      label: "Profile",
      onClick: () => {
        closeAllDropdowns()
        setShowProfileDropdown(true)
      },
      onMouseEnter: () => {
        if (spacesTimeoutRef.current) {
          clearTimeout(spacesTimeoutRef.current)
          spacesTimeoutRef.current = null
        }
        if (planetsTimeoutRef.current) {
          clearTimeout(planetsTimeoutRef.current)
          planetsTimeoutRef.current = null
        }
        if (recentsTimeoutRef.current) {
          clearTimeout(recentsTimeoutRef.current)
          recentsTimeoutRef.current = null
        }
        if (starredTimeoutRef.current) {
          clearTimeout(starredTimeoutRef.current)
          starredTimeoutRef.current = null
        }
        if (signalsTimeoutRef.current) {
          clearTimeout(signalsTimeoutRef.current)
          signalsTimeoutRef.current = null
        }
        setShowSpacesDropdown(false)
        setShowPlanetsDropdown(false)
        setShowRecentsDropdown(false)
        setShowStarredDropdown(false)
        setShowSignalsDropdown(false)
        
        if (profileTimeoutRef.current) {
          clearTimeout(profileTimeoutRef.current)
          profileTimeoutRef.current = null
        }
        setShowProfileDropdown(true)
      },
      onMouseLeave: () => {
        profileTimeoutRef.current = setTimeout(() => {
          setShowProfileDropdown(false)
        }, 150)
      },
    },
  ]
  
  return (
    <>
      {/* Mobile: Overlay backdrop */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[100] md:hidden"
            onClick={() => setIsOpen(false)}
          />
        )}
      </AnimatePresence>
      
      {/* Sidebar */}
      <motion.div
        initial={false}
        animate={{
          x: isOpen ? 0 : -320,
        }}
        transition={{ type: "spring", damping: 25, stiffness: 200 }}
        className={cn(
          "fixed left-0 top-0 h-full z-[101] flex flex-col",
          "bg-white dark:bg-gray-900",
          "border-r border-gray-200 dark:border-gray-800",
          "pointer-events-auto",
          "w-64",
          "md:relative md:z-auto"
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <span className="font-bold text-lg text-gray-900 dark:text-white">GALAXIE</span>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setIsOpen(false)}
            className="h-8 w-8 rounded-lg md:hidden"
          >
            <X className="w-4 h-4" />
          </Button>
        </div>
        
        {/* Navigation */}
        <div className="flex-1 py-4 px-2 overflow-y-auto overflow-x-hidden">
          <div className="space-y-1">
            {navItems.map((item) => {
              const isDropdownOpen = 
                (item.label === "Spaces" && showSpacesDropdown) ||
                (item.label === "Planets" && showPlanetsDropdown) ||
                (item.label === "Recent" && showRecentsDropdown) ||
                (item.label === "Starred" && showStarredDropdown) ||
                (item.label === "Signals" && showSignalsDropdown) ||
                (item.label === "Profile" && showProfileDropdown)
              
              return (
                <div
                  key={item.label}
                  className="relative"
                  onMouseEnter={item.onMouseEnter}
                  onMouseLeave={item.onMouseLeave}
                >
                  <button
                    onClick={item.onClick}
                    className={cn(
                      "w-full text-left flex items-center gap-2 px-3 py-2.5 rounded-md",
                      "transition-all duration-200",
                      "hover:bg-gray-100 dark:hover:bg-gray-800",
                      "text-gray-700 dark:text-gray-300",
                      isDropdownOpen && "bg-gray-100 dark:bg-gray-800",
                      item.label === "Star this planet" && currentPlanet && (() => {
                        try {
                          return isStarred(currentPlanet.id, 'planet')
                        } catch {
                          return false
                        }
                      })() && "text-yellow-500",
                      item.label === "Star this planet" && !currentPlanet && "opacity-50 cursor-not-allowed"
                    )}
                  >
                    <item.icon className="w-4 h-4 shrink-0 text-gray-500 dark:text-gray-400" />
                    <span className="text-sm flex-1">{item.label}</span>
                    {!item.isAction && (
                      <ChevronRight className={cn(
                        "w-3 h-3 transition-transform shrink-0",
                        isDropdownOpen && "rotate-90"
                      )} />
                    )}
                  </button>
                  
                  {/* Dropdowns */}
                  <>
                    {item.label === "Spaces" && (
                      <SpacesDropdown
                        isOpen={showSpacesDropdown}
                        onOpenChange={setShowSpacesDropdown}
                        onClose={closeAllDropdowns}
                      />
                    )}
                    {item.label === "Planets" && (
                      <PlanetsDropdown
                        isOpen={showPlanetsDropdown}
                        onOpenChange={setShowPlanetsDropdown}
                        onClose={closeAllDropdowns}
                      />
                    )}
                    {item.label === "Recent" && (
                      <RecentsDropdown
                        isOpen={showRecentsDropdown}
                        onOpenChange={setShowRecentsDropdown}
                        onClose={closeAllDropdowns}
                      />
                    )}
                    {item.label === "Starred" && (
                      <StarredDropdown
                        isOpen={showStarredDropdown}
                        onOpenChange={setShowStarredDropdown}
                        onClose={closeAllDropdowns}
                      />
                    )}
                    {item.label === "Signals" && (
                      <SignalsDropdown
                        isOpen={showSignalsDropdown}
                        onOpenChange={setShowSignalsDropdown}
                        onClose={closeAllDropdowns}
                      />
                    )}
                    {item.label === "Profile" && (
                      <ProfileDropdown
                        isOpen={showProfileDropdown}
                        onOpenChange={setShowProfileDropdown}
                        onClose={closeAllDropdowns}
                      />
                    )}
                  </>
                </div>
              )
            })}
          </div>
        </div>
      </motion.div>
      
      {/* Create Planet Dialog */}
      <CreatePlanetDialog
        open={showCreatePlanetDialog}
        onOpenChange={setShowCreatePlanetDialog}
      />
    </>
  )
}

