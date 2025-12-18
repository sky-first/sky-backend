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
  
  // Track if any dialog is open
  const [hasOpenDialog, setHasOpenDialog] = useState(false)
  
  // Timeout refs for hover behavior
  const spacesTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const crewsTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const planetsTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const recentsTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const starredTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const signalsTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const sidebarCloseTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  
  // Close on escape key or click outside
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        setIsOpen(false)
      }
    }
    
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      // Don't close if clicking on dialog content or overlay
      if (target.closest('[data-slot="dialog-content"]') || target.closest('[data-slot="dialog-overlay"]')) {
        return
      }
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
  
  // Monitor for open dialogs
  useEffect(() => {
    const checkDialogs = () => {
      const dialogOpen = !!(document.querySelector('[data-slot="dialog-content"][data-state="open"]') || 
                           document.querySelector('[data-slot="dialog-overlay"][data-state="open"]'))
      setHasOpenDialog(dialogOpen)
    }
    
    checkDialogs()
    const interval = setInterval(checkDialogs, 100)
    return () => clearInterval(interval)
  }, [])
  
  // Close all dropdowns when sidebar closes
  useEffect(() => {
    if (!isOpen) {
      if (!hasOpenDialog) {
        // Only close dropdowns if no dialog is open
      setShowSpacesDropdown(false)
      setShowCrewsDropdown(false)
      setShowPlanetsDropdown(false)
      setShowRecentsDropdown(false)
      setShowStarredDropdown(false)
      setShowSignalsDropdown(false)
    }
      // Clear sidebar close timeout when sidebar closes
      if (sidebarCloseTimeoutRef.current) {
        clearTimeout(sidebarCloseTimeoutRef.current)
        sidebarCloseTimeoutRef.current = null
      }
    }
    // Cleanup timeout on unmount
    return () => {
      if (sidebarCloseTimeoutRef.current) {
        clearTimeout(sidebarCloseTimeoutRef.current)
        sidebarCloseTimeoutRef.current = null
      }
    }
  }, [isOpen, hasOpenDialog])
  
  const closeAllDropdowns = () => {
    // Only close dropdowns if no dialog is open
    if (!hasOpenDialog) {
    setShowSpacesDropdown(false)
    setShowCrewsDropdown(false)
    setShowPlanetsDropdown(false)
    setShowRecentsDropdown(false)
    setShowStarredDropdown(false)
    setShowSignalsDropdown(false)
    }
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
        // Allow cursor travel into dropdown before closing
        if (spacesTimeoutRef.current) {
          clearTimeout(spacesTimeoutRef.current)
        }
        spacesTimeoutRef.current = setTimeout(() => {
          setShowSpacesDropdown(false)
          spacesTimeoutRef.current = null
        }, 150)
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
        // Allow cursor travel into dropdown before closing
        if (crewsTimeoutRef.current) {
          clearTimeout(crewsTimeoutRef.current)
        }
        crewsTimeoutRef.current = setTimeout(() => {
          setShowCrewsDropdown(false)
          crewsTimeoutRef.current = null
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
        // Allow cursor travel into dropdown before closing
        if (planetsTimeoutRef.current) {
          clearTimeout(planetsTimeoutRef.current)
        }
        planetsTimeoutRef.current = setTimeout(() => {
          setShowPlanetsDropdown(false)
          planetsTimeoutRef.current = null
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
        // Allow cursor travel into dropdown before closing
        if (recentsTimeoutRef.current) {
          clearTimeout(recentsTimeoutRef.current)
        }
        recentsTimeoutRef.current = setTimeout(() => {
          setShowRecentsDropdown(false)
          recentsTimeoutRef.current = null
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
        // Allow cursor travel into dropdown before closing
        if (starredTimeoutRef.current) {
          clearTimeout(starredTimeoutRef.current)
        }
        starredTimeoutRef.current = setTimeout(() => {
          setShowStarredDropdown(false)
          starredTimeoutRef.current = null
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
        // Allow cursor travel into dropdown before closing
        if (signalsTimeoutRef.current) {
          clearTimeout(signalsTimeoutRef.current)
        }
        signalsTimeoutRef.current = setTimeout(() => {
          setShowSignalsDropdown(false)
          signalsTimeoutRef.current = null
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
            onMouseEnter={() => {
              // Cancel timeout if mouse re-enters the sidebar
              if (sidebarCloseTimeoutRef.current) {
                clearTimeout(sidebarCloseTimeoutRef.current)
                sidebarCloseTimeoutRef.current = null
              }
            }}
            onMouseLeave={() => {
              // Close all dropdowns when mouse leaves the entire sidebar
              closeAllDropdowns()
              // Use a small timeout before closing to allow movement between elements
              if (sidebarCloseTimeoutRef.current) {
                clearTimeout(sidebarCloseTimeoutRef.current)
              }
              sidebarCloseTimeoutRef.current = setTimeout(() => {
                setIsOpen(false)
                sidebarCloseTimeoutRef.current = null
              }, 100)
            }}
          >
            {/* Left Panel - Main Navigation */}
            <div 
              className={cn(
              "w-64 flex flex-col flex-shrink-0",
              "bg-gray-50 dark:bg-gray-900/50",
              "border-r border-gray-200 dark:border-gray-800"
              )}
              onMouseEnter={() => {
                // Cancel sidebar close timeout when mouse enters left panel
                if (sidebarCloseTimeoutRef.current) {
                  clearTimeout(sidebarCloseTimeoutRef.current)
                  sidebarCloseTimeoutRef.current = null
                }
              }}
            >
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
                  onCloseSidebar={() => setIsOpen(false)}
                  onMouseEnter={() => {
                    // Cancel timeout from menu item
                    if (spacesTimeoutRef.current) {
                      clearTimeout(spacesTimeoutRef.current)
                      spacesTimeoutRef.current = null
                    }
                    // Cancel sidebar close timeout
                    if (sidebarCloseTimeoutRef.current) {
                      clearTimeout(sidebarCloseTimeoutRef.current)
                      sidebarCloseTimeoutRef.current = null
                    }
                  }}
                  onMouseLeave={() => {
                    if (spacesTimeoutRef.current) {
                      clearTimeout(spacesTimeoutRef.current)
                      spacesTimeoutRef.current = null
                    }
                      setShowSpacesDropdown(false)
                  }}
                />
              )}
              {showCrewsDropdown && (
                <CrewsDropdown
                  isOpen={showCrewsDropdown}
                  onOpenChange={setShowCrewsDropdown}
                  onClose={closeAllDropdowns}
                  onCloseSidebar={() => setIsOpen(false)}
                  onMouseEnter={() => {
                    // Cancel timeout from menu item
                    if (crewsTimeoutRef.current) {
                      clearTimeout(crewsTimeoutRef.current)
                      crewsTimeoutRef.current = null
                    }
                    // Cancel sidebar close timeout
                    if (sidebarCloseTimeoutRef.current) {
                      clearTimeout(sidebarCloseTimeoutRef.current)
                      sidebarCloseTimeoutRef.current = null
                    }
                  }}
                  onMouseLeave={() => {
                    if (crewsTimeoutRef.current) {
                      clearTimeout(crewsTimeoutRef.current)
                      crewsTimeoutRef.current = null
                    }
                      setShowCrewsDropdown(false)
                  }}
                />
              )}
              {showPlanetsDropdown && (
                <PlanetsDropdown
                  isOpen={showPlanetsDropdown}
                  onOpenChange={setShowPlanetsDropdown}
                  onClose={closeAllDropdowns}
                  onCloseSidebar={() => setIsOpen(false)}
                  onMouseEnter={() => {
                    // Cancel timeout from menu item
                    if (planetsTimeoutRef.current) {
                      clearTimeout(planetsTimeoutRef.current)
                      planetsTimeoutRef.current = null
                    }
                    // Cancel sidebar close timeout
                    if (sidebarCloseTimeoutRef.current) {
                      clearTimeout(sidebarCloseTimeoutRef.current)
                      sidebarCloseTimeoutRef.current = null
                    }
                  }}
                  onMouseLeave={() => {
                    if (planetsTimeoutRef.current) {
                      clearTimeout(planetsTimeoutRef.current)
                      planetsTimeoutRef.current = null
                    }
                      setShowPlanetsDropdown(false)
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
                    // Cancel sidebar close timeout
                    if (sidebarCloseTimeoutRef.current) {
                      clearTimeout(sidebarCloseTimeoutRef.current)
                      sidebarCloseTimeoutRef.current = null
                    }
                  }}
                  onMouseLeave={() => {
                    if (recentsTimeoutRef.current) {
                      clearTimeout(recentsTimeoutRef.current)
                      recentsTimeoutRef.current = null
                    }
                      setShowRecentsDropdown(false)
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
                    // Cancel sidebar close timeout
                    if (sidebarCloseTimeoutRef.current) {
                      clearTimeout(sidebarCloseTimeoutRef.current)
                      sidebarCloseTimeoutRef.current = null
                    }
                  }}
                  onMouseLeave={() => {
                    if (starredTimeoutRef.current) {
                      clearTimeout(starredTimeoutRef.current)
                      starredTimeoutRef.current = null
                    }
                      setShowStarredDropdown(false)
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
                    // Cancel sidebar close timeout
                    if (sidebarCloseTimeoutRef.current) {
                      clearTimeout(sidebarCloseTimeoutRef.current)
                      sidebarCloseTimeoutRef.current = null
                    }
                  }}
                  onMouseLeave={() => {
                    if (signalsTimeoutRef.current) {
                      clearTimeout(signalsTimeoutRef.current)
                      signalsTimeoutRef.current = null
                    }
                      setShowSignalsDropdown(false)
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
      
      {/* Render dropdowns outside sidebar when they have open dialogs and sidebar is closed */}
      {!isOpen && hasOpenDialog && (
        <>
          {showSpacesDropdown && (
            <div style={{ position: 'absolute', left: '-9999px', visibility: 'hidden', pointerEvents: 'none' }}>
              <SpacesDropdown
                isOpen={showSpacesDropdown}
                onOpenChange={setShowSpacesDropdown}
                onClose={() => {}}
                onCloseSidebar={() => setIsOpen(false)}
              />
            </div>
          )}
          {showCrewsDropdown && (
            <div style={{ position: 'absolute', left: '-9999px', visibility: 'hidden', pointerEvents: 'none' }}>
              <CrewsDropdown
                isOpen={showCrewsDropdown}
                onOpenChange={setShowCrewsDropdown}
                onClose={() => {}}
                onCloseSidebar={() => setIsOpen(false)}
              />
            </div>
          )}
          {showPlanetsDropdown && (
            <div style={{ position: 'absolute', left: '-9999px', visibility: 'hidden', pointerEvents: 'none' }}>
              <PlanetsDropdown
                isOpen={showPlanetsDropdown}
                onOpenChange={setShowPlanetsDropdown}
                onClose={() => {}}
                onCloseSidebar={() => setIsOpen(false)}
              />
            </div>
          )}
        </>
      )}
    </>
  )
}

