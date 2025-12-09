"use client"

import { useState, useMemo, useEffect } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { usePlanetStore, type Planet } from "@/store/planet-store"
import { useTheme } from "next-themes"
import { CreatePlanetDialog } from "@/components/workspaces/create-workspace-dialog"
import { 
    Users, 
    User, 
    Search, 
    Plus, 
    Check, 
    Building2,
    Sparkles,
    ArrowRight,
    Clock
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

interface PlanetsDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
}

const colorClasses = {
    blue: "from-blue-500 to-blue-600",
    purple: "from-purple-500 to-purple-600",
    green: "from-green-500 to-green-600",
    orange: "from-orange-500 to-orange-600",
    pink: "from-pink-500 to-pink-600",
    indigo: "from-indigo-500 to-indigo-600",
    teal: "from-teal-500 to-teal-600",
    red: "from-red-500 to-red-600",
}

const colorBorders = {
    blue: "border-blue-200 dark:border-blue-800",
    purple: "border-purple-200 dark:border-purple-800",
    green: "border-green-200 dark:border-green-800",
    orange: "border-orange-200 dark:border-orange-800",
    pink: "border-pink-200 dark:border-pink-800",
    indigo: "border-indigo-200 dark:border-indigo-800",
    teal: "border-teal-200 dark:border-teal-800",
    red: "border-red-200 dark:border-red-800",
}

const colorHovers = {
    blue: "hover:border-blue-300 dark:hover:border-blue-700",
    purple: "hover:border-purple-300 dark:hover:border-purple-700",
    green: "hover:border-green-300 dark:hover:border-green-700",
    orange: "hover:border-orange-300 dark:hover:border-orange-700",
    pink: "hover:border-pink-300 dark:hover:border-pink-700",
    indigo: "hover:border-indigo-300 dark:hover:border-indigo-700",
    teal: "hover:border-teal-300 dark:hover:border-teal-700",
    red: "hover:border-red-300 dark:hover:border-red-700",
}

function formatLastAccessed(date: Date | undefined): string {
    if (!date) return "Nunca acessado"
    
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const days = Math.floor(diff / (1000 * 60 * 60 * 24))
    
    if (days === 0) return "Hoje"
    if (days === 1) return "Ontem"
    if (days < 7) return `${days} dias atrás`
    if (days < 30) return `${Math.floor(days / 7)} semanas atrás`
    return `${Math.floor(days / 30)} meses atrás`
}

function PlanetCard({ 
    planet, 
    onClick 
}: { 
    planet: Planet
    onClick: () => void 
}) {
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === 'dark'
    const color = planet.color as keyof typeof colorClasses
    
    return (
        <button
            onClick={onClick}
            className={cn(
                "group relative w-full text-left",
                "rounded-2xl border-2 transition-all duration-300",
                "bg-white/50 dark:bg-gray-900/50 backdrop-blur-sm",
                colorBorders[color] || colorBorders.blue,
                colorHovers[color] || colorHovers.blue,
                planet.isActive 
                    ? "ring-2 ring-offset-2 ring-blue-500 dark:ring-blue-400 scale-[1.02]" 
                    : "hover:scale-[1.02] hover:shadow-xl",
                "overflow-hidden"
            )}
        >
            {/* Gradient Background */}
            <div className={cn(
                "absolute inset-0 opacity-5 group-hover:opacity-10 transition-opacity duration-300",
                `bg-gradient-to-br ${colorClasses[color] || colorClasses.blue}`
            )} />
            
            <div className="relative p-5 space-y-3">
                {/* Header */}
                <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3 flex-1 min-w-0">
                        {/* Icon */}
                        <div className={cn(
                            "flex-shrink-0 w-12 h-12 rounded-xl flex items-center justify-center",
                            "bg-gradient-to-br shadow-lg",
                            colorClasses[color] || colorClasses.blue,
                            "text-white"
                        )}>
                            {planet.type === 'team' ? (
                                <Users className="w-6 h-6" />
                            ) : (
                                <User className="w-6 h-6" />
                            )}
                        </div>
                        
                        {/* Title and Type */}
                        <div className="flex-1 min-w-0">
                            <h3 className={cn(
                                "font-semibold text-base truncate",
                                isDark ? "text-white" : "text-gray-900"
                            )}>
                                {planet.name}
                            </h3>
                            <div className="flex items-center gap-2 mt-0.5">
                                <span className={cn(
                                    "text-xs font-medium px-2 py-0.5 rounded-full",
                                    planet.type === 'team'
                                        ? "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300"
                                        : "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                                )}>
                                    {planet.type === 'team' ? 'Time' : 'Pessoal'}
                                </span>
                            </div>
                        </div>
                    </div>
                    
                    {/* Active Indicator */}
                    {planet.isActive && (
                        <div className="flex-shrink-0">
                            <div className="w-6 h-6 rounded-full bg-blue-500 dark:bg-blue-400 flex items-center justify-center">
                                <Check className="w-4 h-4 text-white" />
                            </div>
                        </div>
                    )}
                </div>
                
                {/* Description */}
                {planet.description && (
                    <p className={cn(
                        "text-sm line-clamp-2",
                        isDark ? "text-gray-400" : "text-gray-600"
                    )}>
                        {planet.description}
                    </p>
                )}
                
                {/* Footer Info */}
                <div className="flex items-center justify-between pt-2 border-t border-gray-200 dark:border-gray-800">
                    {planet.type === 'team' && planet.memberCount && (
                        <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
                            <Users className="w-3.5 h-3.5" />
                            <span>{planet.memberCount} membros</span>
                        </div>
                    )}
                    <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400 ml-auto">
                        <Clock className="w-3.5 h-3.5" />
                        <span>{formatLastAccessed(planet.lastAccessed)}</span>
                    </div>
                </div>
            </div>
            
            {/* Hover Arrow */}
            <div className={cn(
                "absolute right-4 top-1/2 -translate-y-1/2",
                "opacity-0 group-hover:opacity-100 transition-opacity duration-300",
                "text-gray-400 dark:text-gray-500"
            )}>
                <ArrowRight className="w-5 h-5" />
            </div>
        </button>
    )
}

export function PlanetsDialog({ open, onOpenChange }: PlanetsDialogProps) {
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === 'dark'
    const [searchQuery, setSearchQuery] = useState("")
    const [showCreatePlanetDialog, setShowCreatePlanetDialog] = useState(false)
    
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
    
    // Fetch planets when dialog opens
    useEffect(() => {
        if (open && planets.length === 0) {
            fetchPlanets().catch(console.error)
        }
    }, [open, planets.length, fetchPlanets])
    
    const personalPlanets = useMemo(() => getPersonalPlanets(), [getPersonalPlanets, planets])
    const teamPlanets = useMemo(() => getTeamPlanets(), [getTeamPlanets, planets])
    
    const filteredPersonal = useMemo(() => {
        if (!searchQuery) return personalPlanets
        const query = searchQuery.toLowerCase()
        return personalPlanets.filter(
            (w) => w.name.toLowerCase().includes(query) || 
                  w.description?.toLowerCase().includes(query)
        )
    }, [personalPlanets, searchQuery])
    
    const filteredTeam = useMemo(() => {
        if (!searchQuery) return teamPlanets
        const query = searchQuery.toLowerCase()
        return teamPlanets.filter(
            (w) => w.name.toLowerCase().includes(query) || 
                  w.description?.toLowerCase().includes(query)
        )
    }, [teamPlanets, searchQuery])
    
    const handlePlanetClick = async (planet: Planet) => {
        try {
            // Switch planet via API
            await switchPlanet(planet.id)
            onOpenChange(false)
        } catch (error) {
            console.error('Error switching planet:', error)
            // Fallback to local state update
            setCurrentPlanet(planet)
            onOpenChange(false)
        }
    }
    
    const handleCreatePlanet = () => {
        setShowCreatePlanetDialog(true)
    }
    
    return (
        <>
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className={cn(
                "max-w-4xl w-full max-h-[85vh] p-0 gap-0",
                "bg-white/80 dark:bg-gray-900/80 backdrop-blur-xl",
                "border-gray-200 dark:border-gray-800"
            )}>
                {/* Header */}
                <DialogHeader className="px-6 pt-6 pb-4 border-b border-gray-200 dark:border-gray-800">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <div className={cn(
                                "w-10 h-10 rounded-xl flex items-center justify-center",
                                "bg-gradient-to-br from-blue-500 to-purple-600",
                                "shadow-lg"
                            )}>
                                <Building2 className="w-5 h-5 text-white" />
                            </div>
                            <div>
                                <DialogTitle className={cn(
                                    "text-2xl font-bold",
                                    isDark ? "text-white" : "text-gray-900"
                                )}>
                                    Espaços de Trabalho
                                </DialogTitle>
                                <p className={cn(
                                    "text-sm mt-0.5",
                                    isDark ? "text-gray-400" : "text-gray-600"
                                )}>
                                    Gerencie seus planets pessoais e de time
                                </p>
                            </div>
                        </div>
                        <Button
                            onClick={handleCreatePlanet}
                            className={cn(
                                "gap-2 shadow-lg",
                                "bg-gradient-to-r from-blue-500 to-purple-600",
                                "hover:from-blue-600 hover:to-purple-700",
                                "text-white border-0"
                            )}
                        >
                            <Plus className="w-4 h-4" />
                            Novo Planet
                        </Button>
                    </div>
                </DialogHeader>
                
                {/* Search Bar */}
                <div className="px-6 pt-4 pb-2">
                    <div className="relative">
                        <Search className={cn(
                            "absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4",
                            isDark ? "text-gray-500" : "text-gray-400"
                        )} />
                        <input
                            type="text"
                            placeholder="Buscar planets..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className={cn(
                                "w-full pl-10 pr-4 py-2.5 rounded-xl",
                                "bg-gray-100 dark:bg-gray-800",
                                "border border-gray-200 dark:border-gray-700",
                                "text-sm",
                                "focus:outline-none focus:ring-2 focus:ring-blue-500/50",
                                "placeholder:text-gray-400 dark:placeholder:text-gray-500",
                                isDark ? "text-white" : "text-gray-900"
                            )}
                        />
                    </div>
                </div>
                
                {/* Content */}
                <div className="px-6 pb-6 pt-4 overflow-y-auto max-h-[calc(85vh-200px)]">
                    <div className="space-y-6">
                        {/* Personal Planets */}
                        <div className="space-y-3">
                            <div className="flex items-center gap-2">
                                <User className={cn(
                                    "w-5 h-5",
                                    isDark ? "text-blue-400" : "text-blue-600"
                                )} />
                                <h2 className={cn(
                                    "text-lg font-semibold",
                                    isDark ? "text-white" : "text-gray-900"
                                )}>
                                    Meus Planets
                                </h2>
                                <span className={cn(
                                    "text-xs px-2 py-0.5 rounded-full",
                                    "bg-blue-100 dark:bg-blue-900/30",
                                    "text-blue-700 dark:text-blue-300"
                                )}>
                                    {filteredPersonal.length}
                                </span>
                            </div>
                            
                            {filteredPersonal.length > 0 ? (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    {filteredPersonal.map((planet) => (
                                        <PlanetCard
                                            key={planet.id}
                                            planet={planet}
                                            onClick={() => handlePlanetClick(planet)}
                                        />
                                    ))}
                                </div>
                            ) : (
                                <div className={cn(
                                    "text-center py-8 rounded-xl",
                                    "bg-gray-50 dark:bg-gray-800/50",
                                    "border border-dashed border-gray-300 dark:border-gray-700"
                                )}>
                                    <Sparkles className={cn(
                                        "w-12 h-12 mx-auto mb-3",
                                        isDark ? "text-gray-600" : "text-gray-400"
                                    )} />
                                    <p className={cn(
                                        "text-sm",
                                        isDark ? "text-gray-400" : "text-gray-600"
                                    )}>
                                        {searchQuery 
                                            ? "Nenhum planet pessoal encontrado" 
                                            : "Você ainda não tem planets pessoais"}
                                    </p>
                                </div>
                            )}
                        </div>
                        
                        {/* Team Planets */}
                        <div className="space-y-3">
                            <div className="flex items-center gap-2">
                                <Users className={cn(
                                    "w-5 h-5",
                                    isDark ? "text-purple-400" : "text-purple-600"
                                )} />
                                <h2 className={cn(
                                    "text-lg font-semibold",
                                    isDark ? "text-white" : "text-gray-900"
                                )}>
                                    Planets do Time
                                </h2>
                                <span className={cn(
                                    "text-xs px-2 py-0.5 rounded-full",
                                    "bg-purple-100 dark:bg-purple-900/30",
                                    "text-purple-700 dark:text-purple-300"
                                )}>
                                    {filteredTeam.length}
                                </span>
                            </div>
                            
                            {filteredTeam.length > 0 ? (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    {filteredTeam.map((planet) => (
                                            <PlanetCard
                                                key={planet.id}
                                                planet={planet}
                                                onClick={() => handlePlanetClick(planet)}
                                        />
                                    ))}
                                </div>
                            ) : (
                                <div className={cn(
                                    "text-center py-8 rounded-xl",
                                    "bg-gray-50 dark:bg-gray-800/50",
                                    "border border-dashed border-gray-300 dark:border-gray-700"
                                )}>
                                    <Users className={cn(
                                        "w-12 h-12 mx-auto mb-3",
                                        isDark ? "text-gray-600" : "text-gray-400"
                                    )} />
                                    <p className={cn(
                                        "text-sm",
                                        isDark ? "text-gray-400" : "text-gray-600"
                                    )}>
                                        {searchQuery 
                                            ? "Nenhum planet de time encontrado" 
                                            : "Você ainda não tem acesso a planets de time"}
                                    </p>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </DialogContent>
        </Dialog>

        {/* Create Planet Dialog */}
        <CreatePlanetDialog 
            open={showCreatePlanetDialog}
            onOpenChange={setShowCreatePlanetDialog}
        />
        </>
    )
}

