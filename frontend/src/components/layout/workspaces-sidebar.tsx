"use client"

import { useEffect, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { X, User, Users, Plus, Clock } from "lucide-react"
import { Button } from "@/components/ui/button"
import { usePlanetSidebarStore } from "@/store/planets-sidebar-store"
import { usePlanetStore, type Planet } from "@/store/planet-store"
import { useTheme } from "next-themes"
import { cn } from "@/lib/utils"
import { Separator } from "@/components/ui/separator"
// CreatePlanetDialog import - check if file exists
// import { CreatePlanetDialog } from "@/components/planets/create-planet-dialog"

function formatLastAccessed(date: Date | undefined): string {
    if (!date) return "Nunca"
    
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const days = Math.floor(diff / (1000 * 60 * 60 * 24))
    
    if (days === 0) return "Hoje"
    if (days === 1) return "Ontem"
    if (days < 7) return `${days}d atrás`
    if (days < 30) return `${Math.floor(days / 7)}s atrás`
    return `${Math.floor(days / 30)}m atrás`
}

function PlanetItem({ 
    planet, 
    onClick 
}: { 
    planet: Planet
    onClick: () => void 
}) {
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === 'dark'
    
    return (
        <button
            onClick={onClick}
            className={cn(
                "w-full text-left px-3 py-2.5 rounded-lg",
                "transition-all duration-200",
                planet.isActive
                    ? "bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300"
                    : "hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300",
                "group"
            )}
        >
            <div className="flex items-center gap-3">
                <div className={cn(
                    "flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center",
                    planet.isActive
                        ? "bg-blue-500 dark:bg-blue-600 text-white"
                        : "bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-gray-300 dark:group-hover:bg-gray-600"
                )}>
                    {planet.type === 'team' ? (
                        <Users className="w-4 h-4" />
                    ) : (
                        <User className="w-4 h-4" />
                    )}
                </div>
                <div className="flex-1 min-w-0">
                    <div className={cn(
                        "text-sm font-medium truncate",
                        planet.isActive 
                            ? "text-blue-700 dark:text-blue-300" 
                            : "text-gray-900 dark:text-gray-100"
                    )}>
                        {planet.name}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                        <span className={cn(
                            "text-xs",
                            planet.isActive
                                ? "text-blue-600 dark:text-blue-400"
                                : "text-gray-500 dark:text-gray-400"
                        )}>
                            {planet.type === 'team' ? 'Time' : 'Pessoal'}
                        </span>
                        {planet.type === 'team' && planet.memberCount && (
                            <>
                                <span className="text-gray-300 dark:text-gray-600">•</span>
                                <span className={cn(
                                    "text-xs",
                                    planet.isActive
                                        ? "text-blue-600 dark:text-blue-400"
                                        : "text-gray-500 dark:text-gray-400"
                                )}>
                                    {planet.memberCount} membros
                                </span>
                            </>
                        )}
                    </div>
                </div>
                <div className={cn(
                    "text-xs flex-shrink-0",
                    planet.isActive
                        ? "text-blue-600 dark:text-blue-400"
                        : "text-gray-400 dark:text-gray-500"
                )}>
                    {formatLastAccessed(planet.lastAccessed)}
                </div>
            </div>
        </button>
    )
}

export function PlanetsSidebar() {
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === 'dark'
    const { isOpen, setIsOpen } = usePlanetSidebarStore()
    // const [showCreatePlanetDialog, setShowCreatePlanetDialog] = useState(false) // TODO: Add CreatePlanetDialog component
    const {
        planets,
        currentPlanet,
        setCurrentPlanet,
        getPersonalPlanets,
        getTeamPlanets,
        switchPlanet,
        fetchPlanets,
        isLoading,
    } = usePlanetStore()

    const personalPlanets = getPersonalPlanets()
    const teamPlanets = getTeamPlanets()

    // Fetch planets when sidebar opens
    useEffect(() => {
        if (isOpen && planets.length === 0) {
            fetchPlanets().catch(console.error)
        }
    }, [isOpen, planets.length, fetchPlanets])

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

    const handlePlanetClick = async (planet: Planet) => {
        try {
            // Switch planet via API
            await switchPlanet(planet.id)
            setIsOpen(false)
        } catch (error) {
            console.error('Error switching planet:', error)
            // Fallback to local state update
            setCurrentPlanet(planet)
            setIsOpen(false)
        }
    }

    // const handleCreatePlanet = () => {
    //     setShowCreatePlanetDialog(true)
    // } // TODO: Add CreatePlanetDialog component

    return (
        <AnimatePresence>
            {isOpen && (
                <>
                    {/* Backdrop */}
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[100]"
                        onClick={() => setIsOpen(false)}
                    />

                    {/* Sidebar */}
                    <motion.div
                        initial={{ x: -320 }}
                        animate={{ x: 0 }}
                        exit={{ x: -320 }}
                        transition={{ type: "spring", damping: 25, stiffness: 200 }}
                        className={cn(
                            "fixed left-0 top-0 h-full w-80 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 shadow-2xl z-[101] flex flex-col pointer-events-auto"
                        )}
                        onClick={(e) => e.stopPropagation()}
                    >
                        {/* Header */}
                        <div className={cn(
                            "px-4 py-4 flex items-center justify-between border-b",
                            "border-gray-200 dark:border-gray-800"
                        )}>
                            <h2 className={cn(
                                "text-lg font-semibold",
                                isDark ? "text-white" : "text-gray-900"
                            )}>
                                Planets
                            </h2>
                            <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => setIsOpen(false)}
                                className="h-8 w-8 rounded-lg"
                            >
                                <X className="w-4 h-4" />
                            </Button>
                        </div>

                        {/* Content */}
                        <div className="flex-1 overflow-y-auto px-3 py-4">
                            {/* Personal Planets */}
                            {personalPlanets.length > 0 && (
                                <div className="mb-6">
                                    <div className="px-2 mb-2">
                                        <span className={cn(
                                            "text-xs font-semibold uppercase tracking-wider",
                                            isDark ? "text-gray-400" : "text-gray-500"
                                        )}>
                                            Meus Planets
                                        </span>
                                    </div>
                                    <div className="space-y-1">
                                        {personalPlanets.map((planet) => (
                                            <PlanetItem
                                                key={planet.id}
                                                planet={planet}
                                                onClick={() => handlePlanetClick(planet)}
                                            />
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Team Planets */}
                            {teamPlanets.length > 0 && (
                                <div>
                                    <div className="px-2 mb-2">
                                        <span className={cn(
                                            "text-xs font-semibold uppercase tracking-wider",
                                            isDark ? "text-gray-400" : "text-gray-500"
                                        )}>
                                            Planets do Time
                                        </span>
                                    </div>
                                    <div className="space-y-1">
                                        {teamPlanets.map((planet) => (
                                            <PlanetItem
                                                key={planet.id}
                                                planet={planet}
                                                onClick={() => handlePlanetClick(planet)}
                                            />
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Empty State */}
                            {personalPlanets.length === 0 && teamPlanets.length === 0 && (
                                <div className={cn(
                                    "text-center py-12 px-4",
                                    "text-gray-500 dark:text-gray-400"
                                )}>
                                    <Users className={cn(
                                        "w-12 h-12 mx-auto mb-3",
                                        "text-gray-300 dark:text-gray-600"
                                    )} />
                                    <p className="text-sm">
                                        Nenhum planet encontrado
                                    </p>
                                </div>
                            )}
                        </div>

                        {/* Footer */}
                        <div className={cn(
                            "px-3 py-4 border-t",
                            "border-gray-200 dark:border-gray-800"
                        )}>
                            <Button
                                onClick={() => {/* TODO: Add CreatePlanetDialog */}}
                                className={cn(
                                    "w-full justify-start gap-2",
                                    "bg-blue-500 hover:bg-blue-600 text-white"
                                )}
                            >
                                <Plus className="w-4 h-4" />
                                Novo Planet
                            </Button>
                        </div>
                    </motion.div>
                </>
            )}
        </AnimatePresence>
    )
}

