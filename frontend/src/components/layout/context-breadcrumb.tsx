"use client"

import { useState, useRef, useEffect, useCallback, useMemo } from "react"
import { usePlanetStore } from "@/store/planet-store"
import { useSpaceStore } from "@/store/space-store"
import { useCrewStore } from "@/store/crew-store"
import { ChevronRight, Folder, Users, ChevronDown, Check } from "lucide-react"
import { cn } from "@/lib/utils"
import { useTheme } from "next-themes"

export function ContextBreadcrumb() {
    // Use Zustand selectors to avoid unnecessary re-renders
    const currentPlanet = usePlanetStore(state => state.currentPlanet)
    const updatePlanet = usePlanetStore(state => state.updatePlanet)
    const currentSpace = useSpaceStore(state => state.currentSpace)
    const spaces = useSpaceStore(state => state.spaces)
    const fetchSpaces = useSpaceStore(state => state.fetchSpaces)
    const setCurrentSpace = useSpaceStore(state => state.setCurrentSpace)
    const currentCrew = useCrewStore(state => state.currentCrew)
    const crews = useCrewStore(state => state.crews)
    const fetchCrews = useCrewStore(state => state.fetchCrews)
    const setCurrentCrew = useCrewStore(state => state.setCurrentCrew)
    
    const { theme, resolvedTheme } = useTheme()
    
    const [mounted, setMounted] = useState(false)
    const [showSpaceMenu, setShowSpaceMenu] = useState(false)
    const [showCrewMenu, setShowCrewMenu] = useState(false)
    const [isUpdatingMode, setIsUpdatingMode] = useState(false)
    
    const spaceMenuRef = useRef<HTMLDivElement>(null)
    const crewMenuRef = useRef<HTMLDivElement>(null)
    const currentSpaceId = currentSpace?.id
    
    useEffect(() => {
        setMounted(true)
    }, [])
    
    // Memoize fetchSpaces and fetchCrews handlers
    const handleFetchSpaces = useCallback(() => {
        if (spaces.length === 0) {
            fetchSpaces().catch(console.error)
        }
    }, [spaces.length, fetchSpaces])
    
    const handleFetchCrews = useCallback(() => {
        if (crews.length === 0 && currentSpaceId) {
            fetchCrews({ space_id: currentSpaceId }).catch(console.error)
        }
    }, [crews.length, currentSpaceId, fetchCrews])
    
    // Fetch data when menus open - optimized dependencies
    useEffect(() => {
        if (showSpaceMenu) {
            handleFetchSpaces()
        }
    }, [showSpaceMenu, handleFetchSpaces])
    
    useEffect(() => {
        if (showCrewMenu) {
            handleFetchCrews()
        }
    }, [showCrewMenu, handleFetchCrews])
    
    // Memoize click outside handler
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (spaceMenuRef.current && !spaceMenuRef.current.contains(event.target as Node)) {
                setShowSpaceMenu(false)
            }
            if (crewMenuRef.current && !crewMenuRef.current.contains(event.target as Node)) {
                setShowCrewMenu(false)
            }
        }
        
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [])
    
    // Memoize theme calculation
    const isDark = useMemo(() => {
        const currentTheme = resolvedTheme || theme || 'light'
        return currentTheme === 'dark'
    }, [resolvedTheme, theme])
    
    // Memoize handlers with useCallback
    const handleSpaceSelect = useCallback((spaceId: string) => {
        const space = spaces.find(s => s.id === spaceId)
        if (space) {
            setCurrentSpace(space)
            setShowSpaceMenu(false)
            setCurrentCrew(null)
        }
    }, [spaces, setCurrentSpace, setCurrentCrew])
    
    const handleCrewSelect = useCallback((crewId: string) => {
        const crew = crews.find(c => c.id === crewId)
        if (crew) {
            setCurrentCrew(crew)
            setShowCrewMenu(false)
        }
    }, [crews, setCurrentCrew])
    
    const handleModeToggle = useCallback(async (mode: 'personal' | 'team') => {
        if (!currentPlanet || isUpdatingMode) return
        
        // Don't update if already in the selected mode
        if (currentPlanet.type === mode) return
        
        setIsUpdatingMode(true)
        try {
            await updatePlanet(currentPlanet.id, { type: mode })
        } catch (error) {
            console.error('Error updating planet mode:', error)
        } finally {
            setIsUpdatingMode(false)
        }
    }, [currentPlanet, isUpdatingMode, updatePlanet])
    
    // Memoize derived values
    const currentMode = useMemo(() => currentPlanet?.type || null, [currentPlanet?.type])
    const isPersonal = useMemo(() => currentMode === 'personal', [currentMode])
    const isCollaborative = useMemo(() => currentMode === 'team', [currentMode])
    const showSpacesAndCrews = useMemo(() => isCollaborative, [isCollaborative])
    
    // Memoize gradient styles
    const activeGradientStyle = useMemo(() => ({
        background: `
            linear-gradient(135deg, #1e3a5f 0%, #2d4a6f 50%, #1a2f4f 100%),
            radial-gradient(2px 2px at 20% 30%, rgba(255, 255, 0, 0.4), transparent),
            radial-gradient(1.5px 1.5px at 60% 70%, rgba(255, 255, 0, 0.3), transparent),
            radial-gradient(1px 1px at 50% 50%, rgba(255, 255, 0, 0.35), transparent),
            radial-gradient(1.5px 1.5px at 80% 10%, rgba(255, 255, 0, 0.3), transparent),
            radial-gradient(2px 2px at 90% 40%, rgba(255, 255, 0, 0.25), transparent),
            radial-gradient(1px 1px at 33% 55%, rgba(255, 255, 0, 0.3), transparent),
            radial-gradient(1.5px 1.5px at 15% 80%, rgba(255, 255, 0, 0.25), transparent),
            radial-gradient(1px 1px at 70% 20%, rgba(255, 255, 0, 0.3), transparent)
        `,
        backgroundColor: '#1e3a5f'
    }), [])
    
    const hoverGradientStyle = useMemo(() => ({
        background: `
            linear-gradient(135deg, #2a4a6f 0%, #3d5a7f 50%, #2a3f5f 100%),
            radial-gradient(2px 2px at 20% 30%, rgba(255, 255, 0, 0.4), transparent),
            radial-gradient(1.5px 1.5px at 60% 70%, rgba(255, 255, 0, 0.3), transparent),
            radial-gradient(1px 1px at 50% 50%, rgba(255, 255, 0, 0.35), transparent),
            radial-gradient(1.5px 1.5px at 80% 10%, rgba(255, 255, 0, 0.3), transparent),
            radial-gradient(2px 2px at 90% 40%, rgba(255, 255, 0, 0.25), transparent),
            radial-gradient(1px 1px at 33% 55%, rgba(255, 255, 0, 0.3), transparent),
            radial-gradient(1.5px 1.5px at 15% 80%, rgba(255, 255, 0, 0.25), transparent),
            radial-gradient(1px 1px at 70% 20%, rgba(255, 255, 0, 0.3), transparent)
        `
    }), [])
    
    const handleToggleSpaceMenu = useCallback(() => {
        setShowSpaceMenu(prev => !prev)
        setShowCrewMenu(false)
    }, [])
    
    const handleToggleCrewMenu = useCallback(() => {
        setShowCrewMenu(prev => !prev)
        setShowSpaceMenu(false)
    }, [])
    
    // Early return after all hooks
    if (!mounted) return null
    
    return (
        <div
            className={cn(
                "fixed top-4 left-1/2 -translate-x-1/2 z-50 pointer-events-none",
                "flex items-center justify-center"
            )}
        >
            <div className={cn(
                "pointer-events-auto",
                "flex items-center gap-1 px-3 py-1.5 rounded-lg",
                "backdrop-blur-xl",
                isDark 
                    ? "bg-gray-900/60 border border-white/10 shadow-lg" 
                    : "bg-white/80 border border-black/10 shadow-lg",
                "transition-all duration-200"
            )}>
                {/* Personal - Collaborative Toggle Button */}
                <div className="relative">
                    <div className={cn(
                        "flex items-center rounded-md overflow-hidden",
                        // Match Sky/Share button height (h-8)
                        "h-8",
                        "border",
                        isDark 
                            ? "border-white/10 bg-gray-800/30" 
                            : "border-gray-200/60 bg-gray-50/40",
                        "transition-all duration-200"
                    )}>
                        {/* Personal Button */}
                        <button
                            onClick={() => handleModeToggle('personal')}
                            disabled={!currentPlanet || isUpdatingMode}
                            className={cn(
                                "relative px-3 py-1 text-sm font-semibold transition-all duration-200",
                                "h-full flex items-center justify-center text-white",
                                isPersonal
                                    ? ""
                                    : isDark 
                                        ? "text-white/60 hover:text-white/80 hover:bg-white/5" 
                                        : "text-gray-500 hover:text-gray-700 hover:bg-white/60",
                                (!currentPlanet || isUpdatingMode) && "opacity-50 cursor-not-allowed",
                                "focus:outline-none"
                            )}
                            style={isPersonal ? activeGradientStyle : undefined}
                            onMouseEnter={(e) => {
                                if (isPersonal && currentPlanet) {
                                    e.currentTarget.style.background = hoverGradientStyle.background || ""
                                } else if (!isPersonal && currentPlanet) {
                                    e.currentTarget.style.background = isDark 
                                        ? "linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.03) 100%)"
                                        : "linear-gradient(135deg, rgba(255,255,255,0.7) 0%, rgba(255,255,255,0.5) 100%)"
                                }
                            }}
                            onMouseLeave={(e) => {
                                if (isPersonal) {
                                    e.currentTarget.style.background = activeGradientStyle.background || ""
                                } else {
                                    e.currentTarget.style.background = ""
                                }
                            }}
                            title={isPersonal 
                                ? "Personal mode: Your work is private and not visible to your crew"
                                : "Switch to Personal mode"}
                        >
                            Personal
                        </button>
                        
                        {/* Divider */}
                        <div className={cn(
                            "w-px h-4",
                            isDark ? "bg-white/8" : "bg-gray-300/60"
                        )} />
                        
                        {/* Collaborative Button */}
                        <button
                            onClick={() => handleModeToggle('team')}
                            disabled={!currentPlanet || isUpdatingMode}
                            className={cn(
                                "relative px-3 py-1 text-sm font-semibold transition-all duration-200",
                                "h-full flex items-center justify-center text-white",
                                isCollaborative
                                    ? ""
                                    : isDark 
                                        ? "text-white/60 hover:text-white/80 hover:bg-white/5" 
                                        : "text-gray-500 hover:text-gray-700 hover:bg-white/60",
                                (!currentPlanet || isUpdatingMode) && "opacity-50 cursor-not-allowed",
                                "focus:outline-none"
                            )}
                            style={isCollaborative ? activeGradientStyle : undefined}
                            onMouseEnter={(e) => {
                                if (isCollaborative && currentPlanet) {
                                    e.currentTarget.style.background = hoverGradientStyle.background || ""
                                } else if (!isCollaborative && currentPlanet) {
                                    e.currentTarget.style.background = isDark 
                                        ? "linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.03) 100%)"
                                        : "linear-gradient(135deg, rgba(255,255,255,0.7) 0%, rgba(255,255,255,0.5) 100%)"
                                }
                            }}
                            onMouseLeave={(e) => {
                                if (isCollaborative) {
                                    e.currentTarget.style.background = activeGradientStyle.background || ""
                                } else {
                                    e.currentTarget.style.background = ""
                                }
                            }}
                            title={isCollaborative 
                                ? "Collaborative mode: Your work is visible to your crew"
                                : "Switch to Collaborative mode"}
                        >
                            Collaborative
                        </button>
                    </div>
                </div>
                
                {/* Separator - Only show in Collaborative mode */}
                {showSpacesAndCrews && (
                    <ChevronRight className={cn(
                        "w-4 h-4",
                        isDark ? "text-white/30" : "text-gray-400"
                    )} />
                )}
                
                {/* Spaces - Only show in Collaborative mode */}
                {showSpacesAndCrews && (
                    <div className="relative" ref={spaceMenuRef}>
                        <button
                            onClick={handleToggleSpaceMenu}
                            className={cn(
                                "flex items-center gap-1.5 px-2 py-1 rounded-md",
                                "text-sm font-semibold transition-all",
                                "hover:bg-white/10 dark:hover:bg-white/5",
                                isDark ? "text-white/90" : "text-gray-900"
                            )}
                        >
                            <Folder className="w-3.5 h-3.5" />
                            <span className="max-w-[120px] truncate">
                                {currentSpace?.name || 'Spaces'}
                            </span>
                            <ChevronDown className={cn(
                                "w-3 h-3 transition-transform",
                                showSpaceMenu && "rotate-180"
                            )} />
                        </button>
                    
                    {showSpaceMenu && (
                        <div className={cn(
                            "absolute top-full left-0 mt-2 w-64",
                            "bg-white dark:bg-gray-800",
                            "rounded-lg shadow-xl border",
                            "border-gray-200 dark:border-gray-700",
                            "py-1 z-50 max-h-[400px] overflow-y-auto"
                        )}>
                            <div className="px-3 py-2 text-sm font-semibold text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
                                Spaces
                            </div>
                            <div className="py-1">
                                {spaces.length === 0 ? (
                                    <div className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">
                                        No spaces available
                                    </div>
                                ) : (
                                    spaces.map((space) => (
                                        <button
                                            key={space.id}
                                            onClick={() => handleSpaceSelect(space.id)}
                                            className={cn(
                                                "w-full text-left flex items-center gap-2 px-3 py-2 text-sm font-medium",
                                                "hover:bg-gray-50 dark:hover:bg-gray-700",
                                                "transition-colors",
                                                currentSpace?.id === space.id && "bg-blue-50 dark:bg-blue-900/20"
                                            )}
                                        >
                                            <Folder className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" />
                                            <span className="flex-1 text-gray-900 dark:text-white">
                                                {space.name}
                                            </span>
                                            {currentSpace?.id === space.id && (
                                                <Check className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
                                            )}
                                        </button>
                                    ))
                                )}
                            </div>
                        </div>
                    )}
                    </div>
                )}
                
                {/* Separator - Only show in Collaborative mode when Crews are visible */}
                {showSpacesAndCrews && (
                    <ChevronRight className={cn(
                        "w-4 h-4",
                        isDark ? "text-white/30" : "text-gray-400"
                    )} />
                )}
                
                {/* Crews - Only show in Collaborative mode */}
                {showSpacesAndCrews && (
                    <div className="relative" ref={crewMenuRef}>
                        <button
                            onClick={handleToggleCrewMenu}
                            className={cn(
                                "flex items-center gap-1.5 px-2 py-1 rounded-md",
                                "text-sm font-semibold transition-all",
                                "hover:bg-white/10 dark:hover:bg-white/5",
                                isDark ? "text-white/90" : "text-gray-900"
                            )}
                        >
                            <Users className="w-3.5 h-3.5" />
                            <span className="max-w-[120px] truncate">
                                {currentCrew?.name || 'Crews'}
                            </span>
                            <ChevronDown className={cn(
                                "w-3 h-3 transition-transform",
                                showCrewMenu && "rotate-180"
                            )} />
                        </button>
                    
                    {showCrewMenu && (
                        <div className={cn(
                            "absolute top-full left-0 mt-2 w-64",
                            "bg-white dark:bg-gray-800",
                            "rounded-lg shadow-xl border",
                            "border-gray-200 dark:border-gray-700",
                            "py-1 z-50 max-h-[400px] overflow-y-auto"
                        )}>
                            <div className="px-3 py-2 text-sm font-semibold text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
                                Crews
                            </div>
                            <div className="py-1">
                                {crews.length === 0 ? (
                                    <div className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">
                                        {currentSpace 
                                            ? "No crews available in this space"
                                            : "Select a space first"}
                                    </div>
                                ) : (
                                    crews.map((crew) => (
                                        <button
                                            key={crew.id}
                                            onClick={() => handleCrewSelect(crew.id)}
                                            className={cn(
                                                "w-full text-left flex items-center gap-2 px-3 py-2 text-sm font-medium",
                                                "hover:bg-gray-50 dark:hover:bg-gray-700",
                                                "transition-colors",
                                                currentCrew?.id === crew.id && "bg-blue-50 dark:bg-blue-900/20"
                                            )}
                                        >
                                            <Users className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" />
                                            <span className="flex-1 text-gray-900 dark:text-white">
                                                {crew.name}
                                            </span>
                                            {currentCrew?.id === crew.id && (
                                                <Check className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
                                            )}
                                        </button>
                                    ))
                                )}
                            </div>
                        </div>
                    )}
                    </div>
                )}
            </div>
        </div>
    )
}
