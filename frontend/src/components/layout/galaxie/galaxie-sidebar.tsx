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
  Menu,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { useSidebarStore } from "@/store/sidebar-store"
import { useUserStore } from "@/store/user-store"
import { usePlanetStore } from "@/store/planet-store"
import { useStarredStore } from "@/store/starred-store"
import { cn } from "@/lib/utils"
import { SpacesDropdown } from "./spaces-dropdown"
import { CrewsDropdown } from "./crews-dropdown"
import { PlanetsDropdown } from "./planets-dropdown"
import { RecentsDropdown } from "./recents-dropdown"
import { StarredDropdown } from "./starred-dropdown"
import { SignalsDropdown } from "./signals-dropdown"
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
  const [showCrewsDropdown, setShowCrewsDropdown] = useState(false)
  const [showPlanetsDropdown, setShowPlanetsDropdown] = useState(false)
  const [showRecentsDropdown, setShowRecentsDropdown] = useState(false)
  const [showStarredDropdown, setShowStarredDropdown] = useState(false)
  const [showSignalsDropdown, setShowSignalsDropdown] = useState(false)
  
  // Timeout refs for hover behavior
  const spacesTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const crewsTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const planetsTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const recentsTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const starredTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const signalsTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  
  // Close on escape key or click outside
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        setIsOpen(false)
      }
    }
    
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      // Close if clicking outside the dropdown and not on the GALAXIE button
      if (isOpen && !target.closest('[data-galaxie-dropdown]') && !target.closest('button[aria-label="Open GALAXIE menu"]')) {
        setIsOpen(false)
      }
    }
    
    document.addEventListener('keydown', handleEscape)
    document.addEventListener('mousedown', handleClickOutside)
    return () => {
      document.removeEventListener('keydown', handleEscape)
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen, setIsOpen])
  
  // Close all dropdowns when sidebar closes
  useEffect(() => {
    if (!isOpen) {
      setShowSpacesDropdown(false)
      setShowCrewsDropdown(false)
      setShowPlanetsDropdown(false)
      setShowRecentsDropdown(false)
      setShowStarredDropdown(false)
      setShowSignalsDropdown(false)
    }
  }, [isOpen])
  
  const closeAllDropdowns = () => {
    setShowSpacesDropdown(false)
    setShowCrewsDropdown(false)
    setShowPlanetsDropdown(false)
    setShowRecentsDropdown(false)
    setShowStarredDropdown(false)
    setShowSignalsDropdown(false)
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
      icon: Folder,
      label: "Spaces",
      onClick: () => {
        closeAllDropdowns()
        setShowSpacesDropdown(true)
      },
      onMouseEnter: () => {
        if (crewsTimeoutRef.current) {
          clearTimeout(crewsTimeoutRef.current)
          crewsTimeoutRef.current = null
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
        setShowCrewsDropdown(false)
        setShowPlanetsDropdown(false)
        setShowRecentsDropdown(false)
        setShowStarredDropdown(false)
        setShowSignalsDropdown(false)
        
        if (spacesTimeoutRef.current) {
          clearTimeout(spacesTimeoutRef.current)
          spacesTimeoutRef.current = null
        }
        setShowSpacesDropdown(true)
      },
      onMouseLeave: () => {
        spacesTimeoutRef.current = setTimeout(() => {
          setShowSpacesDropdown(false)
        }, 200)
      },
    },
    {
      icon: User,
      label: "Crews",
      onClick: () => {
        closeAllDropdowns()
        setShowCrewsDropdown(true)
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
        
        if (crewsTimeoutRef.current) {
          clearTimeout(crewsTimeoutRef.current)
          crewsTimeoutRef.current = null
        }
        setShowCrewsDropdown(true)
      },
      onMouseLeave: () => {
        crewsTimeoutRef.current = setTimeout(() => {
          setShowCrewsDropdown(false)
        }, 200)
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
        if (crewsTimeoutRef.current) {
          clearTimeout(crewsTimeoutRef.current)
          crewsTimeoutRef.current = null
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
        setShowCrewsDropdown(false)
        setShowRecentsDropdown(false)
        setShowStarredDropdown(false)
        setShowSignalsDropdown(false)
        
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
        if (crewsTimeoutRef.current) {
          clearTimeout(crewsTimeoutRef.current)
          crewsTimeoutRef.current = null
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
        setShowSpacesDropdown(false)
        setShowCrewsDropdown(false)
        setShowPlanetsDropdown(false)
        setShowStarredDropdown(false)
        setShowSignalsDropdown(false)
        
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
        if (crewsTimeoutRef.current) {
          clearTimeout(crewsTimeoutRef.current)
          crewsTimeoutRef.current = null
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
        setShowSpacesDropdown(false)
        setShowCrewsDropdown(false)
        setShowPlanetsDropdown(false)
        setShowRecentsDropdown(false)
        setShowSignalsDropdown(false)
        
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
        if (crewsTimeoutRef.current) {
          clearTimeout(crewsTimeoutRef.current)
          crewsTimeoutRef.current = null
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
        setShowSpacesDropdown(false)
        setShowCrewsDropdown(false)
        setShowPlanetsDropdown(false)
        setShowRecentsDropdown(false)
        setShowStarredDropdown(false)
        
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
      icon: Star,
      label: "Star this planet",
      onClick: () => {
        if (currentPlanet) {
          handleStarPlanet()
        }
      },
      isAction: true,
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
      
      {/* Main Menu - Two Panel Layout */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            data-galaxie-dropdown
            initial={{ opacity: 0, y: -10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -10, scale: 0.95 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className={cn(
              "fixed left-4 top-16 z-[101] flex",
              "bg-white dark:bg-gray-900",
              "border border-gray-200 dark:border-gray-800",
              "rounded-lg shadow-2xl",
              "pointer-events-auto",
              "max-h-[calc(100vh-8rem)]",
              "overflow-hidden",
              "md:left-4 md:top-16"
            )}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Left Panel - Main Navigation */}
            <div className={cn(
              "w-64 flex flex-col flex-shrink-0",
              "bg-gray-50 dark:bg-gray-900/50",
              "border-r border-gray-200 dark:border-gray-800"
            )}>
              <div className="py-2 px-2 overflow-y-auto overflow-x-hidden">
                <div className="space-y-1">
                  {navItems.map((item) => {
                    const isDropdownOpen = 
                      (item.label === "Spaces" && showSpacesDropdown) ||
                      (item.label === "Crews" && showCrewsDropdown) ||
                      (item.label === "Planets" && showPlanetsDropdown) ||
                      (item.label === "Recent" && showRecentsDropdown) ||
                      (item.label === "Starred" && showStarredDropdown) ||
                      (item.label === "Signals" && showSignalsDropdown)
                    
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
                            isDropdownOpen && "bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400",
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
                          <item.icon className={cn(
                            "w-4 h-4 shrink-0",
                            isDropdownOpen ? "text-blue-500 dark:text-blue-400" : "text-gray-500 dark:text-gray-400"
                          )} />
                          <span className="text-sm flex-1">{item.label}</span>
                          {!item.isAction && (
                            <ChevronRight className={cn(
                              "w-3 h-3 transition-transform shrink-0",
                              isDropdownOpen && "rotate-90"
                            )} />
                          )}
                        </button>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>

            {/* Right Panel - Lateral Menu */}
            <AnimatePresence mode="wait">
              {showSpacesDropdown && (
                <SpacesDropdown
                  isOpen={showSpacesDropdown}
                  onOpenChange={setShowSpacesDropdown}
                  onClose={closeAllDropdowns}
                  onMouseEnter={() => {
                    // Cancel timeout from menu item
                    if (spacesTimeoutRef.current) {
                      clearTimeout(spacesTimeoutRef.current)
                      spacesTimeoutRef.current = null
                    }
                  }}
                  onMouseLeave={() => {
                    // Start timeout to close dropdown when mouse leaves
                    spacesTimeoutRef.current = setTimeout(() => {
                      setShowSpacesDropdown(false)
                    }, 200)
                  }}
                />
              )}
              {showCrewsDropdown && (
                <CrewsDropdown
                  isOpen={showCrewsDropdown}
                  onOpenChange={setShowCrewsDropdown}
                  onClose={closeAllDropdowns}
                  onMouseEnter={() => {
                    // Cancel timeout from menu item
                    if (crewsTimeoutRef.current) {
                      clearTimeout(crewsTimeoutRef.current)
                      crewsTimeoutRef.current = null
                    }
                  }}
                  onMouseLeave={() => {
                    // Start timeout to close dropdown when mouse leaves
                    crewsTimeoutRef.current = setTimeout(() => {
                      setShowCrewsDropdown(false)
                    }, 200)
                  }}
                />
              )}
              {showPlanetsDropdown && (
                <PlanetsDropdown
                  isOpen={showPlanetsDropdown}
                  onOpenChange={setShowPlanetsDropdown}
                  onClose={closeAllDropdowns}
                  onMouseEnter={() => {
                    // Cancel timeout from menu item
                    if (planetsTimeoutRef.current) {
                      clearTimeout(planetsTimeoutRef.current)
                      planetsTimeoutRef.current = null
                    }
                  }}
                  onMouseLeave={() => {
                    // Start timeout to close dropdown when mouse leaves
                    planetsTimeoutRef.current = setTimeout(() => {
                      setShowPlanetsDropdown(false)
                    }, 200)
                  }}
                />
              )}
              {showRecentsDropdown && (
                <RecentsDropdown
                  isOpen={showRecentsDropdown}
                  onOpenChange={setShowRecentsDropdown}
                  onClose={closeAllDropdowns}
                  onMouseEnter={() => {
                    // Cancel timeout from menu item
                    if (recentsTimeoutRef.current) {
                      clearTimeout(recentsTimeoutRef.current)
                      recentsTimeoutRef.current = null
                    }
                  }}
                  onMouseLeave={() => {
                    // Start timeout to close dropdown when mouse leaves
                    recentsTimeoutRef.current = setTimeout(() => {
                      setShowRecentsDropdown(false)
                    }, 200)
                  }}
                />
              )}
              {showStarredDropdown && (
                <StarredDropdown
                  isOpen={showStarredDropdown}
                  onOpenChange={setShowStarredDropdown}
                  onClose={closeAllDropdowns}
                  onMouseEnter={() => {
                    // Cancel timeout from menu item
                    if (starredTimeoutRef.current) {
                      clearTimeout(starredTimeoutRef.current)
                      starredTimeoutRef.current = null
                    }
                  }}
                  onMouseLeave={() => {
                    // Start timeout to close dropdown when mouse leaves
                    starredTimeoutRef.current = setTimeout(() => {
                      setShowStarredDropdown(false)
                    }, 200)
                  }}
                />
              )}
              {showSignalsDropdown && (
                <SignalsDropdown
                  isOpen={showSignalsDropdown}
                  onOpenChange={setShowSignalsDropdown}
                  onClose={closeAllDropdowns}
                  onMouseEnter={() => {
                    // Cancel timeout from menu item
                    if (signalsTimeoutRef.current) {
                      clearTimeout(signalsTimeoutRef.current)
                      signalsTimeoutRef.current = null
                    }
                  }}
                  onMouseLeave={() => {
                    // Start timeout to close dropdown when mouse leaves
                    signalsTimeoutRef.current = setTimeout(() => {
                      setShowSignalsDropdown(false)
                    }, 200)
                  }}
                />
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
      
      {/* Create Planet Dialog */}
      <CreatePlanetDialog
        open={showCreatePlanetDialog}
        onOpenChange={setShowCreatePlanetDialog}
      />
    </>
  )
}

