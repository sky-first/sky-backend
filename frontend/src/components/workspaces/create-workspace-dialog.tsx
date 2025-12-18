"use client"

import { useState } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { usePlanetStore } from "@/store/planet-store"
import { getDefaultColor, COLOR_MAP } from "@/lib/utils/planet-colors"
import { cn } from "@/lib/utils"
import { Loader2, Sparkles, Users, User } from "lucide-react"
import { useTheme } from "next-themes"

interface CreatePlanetDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
}

const AVAILABLE_COLORS = [
    { name: 'blue', hex: COLOR_MAP.blue, label: 'Azul' },
    { name: 'purple', hex: COLOR_MAP.purple, label: 'Roxo' },
    { name: 'green', hex: COLOR_MAP.green, label: 'Verde' },
    { name: 'orange', hex: COLOR_MAP.orange, label: 'Laranja' },
    { name: 'pink', hex: COLOR_MAP.pink, label: 'Rosa' },
    { name: 'indigo', hex: COLOR_MAP.indigo, label: 'Índigo' },
    { name: 'teal', hex: COLOR_MAP.teal, label: 'Verde-água' },
    { name: 'red', hex: COLOR_MAP.red, label: 'Vermelho' },
]

const colorGradients: Record<string, string> = {
    blue: "from-blue-500 to-blue-600",
    purple: "from-purple-500 to-purple-600",
    green: "from-green-500 to-green-600",
    orange: "from-orange-500 to-orange-600",
    pink: "from-pink-500 to-pink-600",
    indigo: "from-indigo-500 to-indigo-600",
    teal: "from-teal-500 to-teal-600",
    red: "from-red-500 to-red-600",
}

export function CreatePlanetDialog({ open, onOpenChange }: CreatePlanetDialogProps) {
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === 'dark'
    const { createPlanet, fetchPlanets, isLoading } = usePlanetStore()

    const [name, setName] = useState("")
    const [description, setDescription] = useState("")
    const [type, setType] = useState<'personal' | 'team'>('personal')
    const [autoColor, setAutoColor] = useState(true)
    const [selectedColor, setSelectedColor] = useState<string>('blue')
    const [error, setError] = useState<string | null>(null)

    // Reset form when dialog opens/closes
    const handleOpenChange = (newOpen: boolean) => {
        if (!newOpen) {
            // Reset form when closing
            setName("")
            setDescription("")
            setType('personal')
            setAutoColor(true)
            setSelectedColor('blue')
            setError(null)
        }
        onOpenChange(newOpen)
    }

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError(null)

        // Validation
        if (!name.trim()) {
            setError("Nome é obrigatório")
            return
        }

        if (name.trim().length > 255) {
            setError("Nome deve ter no máximo 255 caracteres")
            return
        }

        try {
            // Determine color - pass color name (not hex) since createPlanet will convert it
            const finalColorName = autoColor ? 'blue' : selectedColor

            // Create planet - colorNameToHex will handle the conversion
            await createPlanet({
                name: name.trim(),
                description: description.trim() || undefined,
                type,
                color: finalColorName,
            })

            // Refresh planets list
            await fetchPlanets()

            // Close dialog
            handleOpenChange(false)
        } catch (err) {
            console.error('Error creating planet:', err)
            setError(err instanceof Error ? err.message : 'Erro ao criar planet')
        }
    }

    // Update selected color when type changes and auto color is enabled
    const handleTypeChange = (newType: 'personal' | 'team') => {
        setType(newType)
        if (autoColor) {
            setSelectedColor(newType === 'personal' ? 'blue' : 'purple')
        }
    }

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogContent 
                className="max-w-md"
                onInteractOutside={(e) => {
                    // Check if the click is actually outside the dialog content
                    const target = e.target as HTMLElement
                    const dialogContent = target.closest('[data-slot="dialog-content"]')
                    
                    // If clicking inside the dialog content, prevent closing
                    if (dialogContent) {
                        e.preventDefault()
                    }
                    // Otherwise, allow normal behavior (closing when clicking outside)
                }}
                onPointerDownOutside={(e) => {
                    // Check if the click is actually outside the dialog content
                    const target = e.target as HTMLElement
                    const dialogContent = target.closest('[data-slot="dialog-content"]')
                    
                    // If clicking inside the dialog content, prevent closing
                    if (dialogContent) {
                        e.preventDefault()
                    }
                    // Otherwise, allow normal behavior (closing when clicking outside)
                }}
                onClick={(e) => {
                    // Stop propagation to prevent any parent handlers from closing the dialog
                    // when clicking inside the dialog content
                    e.stopPropagation()
                }}
                onMouseDown={(e) => {
                    // Stop propagation on mouse down as well
                    e.stopPropagation()
                }}
            >
                <DialogHeader
                    onClick={(e) => e.stopPropagation()}
                    onMouseDown={(e) => e.stopPropagation()}
                >
                    <DialogTitle className="flex items-center gap-2">
                        <Sparkles className="w-5 h-5 text-blue-500" />
                        Criar Novo Planet
                    </DialogTitle>
                    <DialogDescription>
                        Crie um novo espaço de trabalho pessoal ou para seu time
                    </DialogDescription>
                </DialogHeader>

                <form 
                    onSubmit={handleSubmit} 
                    className="space-y-4"
                    onClick={(e) => {
                        // Stop propagation to prevent closing dialog when clicking inside form
                        e.stopPropagation()
                    }}
                >
                    {/* Nome */}
                    <div className="space-y-2">
                        <label htmlFor="name" className="text-sm font-medium">
                            Nome <span className="text-red-500">*</span>
                        </label>
                        <Input
                            id="name"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            onClick={(e) => e.stopPropagation()}
                            onMouseDown={(e) => e.stopPropagation()}
                            placeholder="Ex: Meu Projeto"
                            maxLength={255}
                            required
                            disabled={isLoading}
                            className={error && !name.trim() ? "border-red-500" : ""}
                        />
                    </div>

                    {/* Descrição */}
                    <div className="space-y-2">
                        <label htmlFor="description" className="text-sm font-medium">
                            Descrição <span className="text-gray-400 text-xs">(opcional)</span>
                        </label>
                        <Textarea
                            id="description"
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            onClick={(e) => e.stopPropagation()}
                            onMouseDown={(e) => e.stopPropagation()}
                            placeholder="Descreva o propósito deste planet..."
                            rows={3}
                            disabled={isLoading}
                        />
                    </div>

                    {/* Tipo */}
                    <div 
                        className="space-y-2"
                        onClick={(e) => e.stopPropagation()}
                        onMouseDown={(e) => e.stopPropagation()}
                    >
                        <label className="text-sm font-medium">Tipo</label>
                        <div className="flex gap-3">
                            <button
                                type="button"
                                onClick={(e) => {
                                    e.stopPropagation()
                                    handleTypeChange('personal')
                                }}
                                className={cn(
                                    "flex-1 flex items-center gap-2 p-3 rounded-lg border-2 transition-all",
                                    type === 'personal'
                                        ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20"
                                        : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600",
                                    isLoading && "opacity-50 cursor-not-allowed"
                                )}
                                disabled={isLoading}
                            >
                                <User className={cn(
                                    "w-5 h-5",
                                    type === 'personal' ? "text-blue-600 dark:text-blue-400" : "text-gray-400"
                                )} />
                                <div className="text-left">
                                    <div className={cn(
                                        "text-sm font-medium",
                                        type === 'personal' ? "text-blue-700 dark:text-blue-300" : "text-gray-700 dark:text-gray-300"
                                    )}>
                                        Personal
                                    </div>
                                    <div className={cn(
                                        "text-xs",
                                        type === 'personal' ? "text-blue-600 dark:text-blue-400" : "text-gray-500 dark:text-gray-400"
                                    )}>
                                        Espaço pessoal
                                    </div>
                                </div>
                            </button>

                            <button
                                type="button"
                                onClick={(e) => {
                                    e.stopPropagation()
                                    handleTypeChange('team')
                                }}
                                className={cn(
                                    "flex-1 flex items-center gap-2 p-3 rounded-lg border-2 transition-all",
                                    type === 'team'
                                        ? "border-purple-500 bg-purple-50 dark:bg-purple-900/20"
                                        : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600",
                                    isLoading && "opacity-50 cursor-not-allowed"
                                )}
                                disabled={isLoading}
                            >
                                <Users className={cn(
                                    "w-5 h-5",
                                    type === 'team' ? "text-purple-600 dark:text-purple-400" : "text-gray-400"
                                )} />
                                <div className="text-left">
                                    <div className={cn(
                                        "text-sm font-medium",
                                        type === 'team' ? "text-purple-700 dark:text-purple-300" : "text-gray-700 dark:text-gray-300"
                                    )}>
                                        Team
                                    </div>
                                    <div className={cn(
                                        "text-xs",
                                        type === 'team' ? "text-purple-600 dark:text-purple-400" : "text-gray-500 dark:text-gray-400"
                                    )}>
                                        Espaço de time
                                    </div>
                                </div>
                            </button>
                        </div>
                    </div>

                    {/* Cor */}
                    <div 
                        className="space-y-3"
                        onClick={(e) => e.stopPropagation()}
                        onMouseDown={(e) => e.stopPropagation()}
                    >
                        <div className="flex items-center justify-between">
                            <label className="text-sm font-medium">Cor</label>
                            <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400 cursor-pointer">
                                <input
                                    type="checkbox"
                                    checked={autoColor}
                                    onChange={(e) => {
                                        e.stopPropagation()
                                        setAutoColor(e.target.checked)
                                    }}
                                    onClick={(e) => e.stopPropagation()}
                                    onMouseDown={(e) => e.stopPropagation()}
                                    disabled={isLoading}
                                    className="w-4 h-4 rounded border-gray-300 text-blue-500 focus:ring-blue-500"
                                />
                                Gerar automaticamente
                            </label>
                        </div>

                        {!autoColor && (
                            <div className="grid grid-cols-4 gap-2">
                                {AVAILABLE_COLORS.map((color) => (
                                    <button
                                        key={color.name}
                                        type="button"
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            setSelectedColor(color.name)
                                        }}
                                        disabled={isLoading}
                                        className={cn(
                                            "relative aspect-square rounded-lg border-2 transition-all",
                                            "bg-gradient-to-br",
                                            colorGradients[color.name],
                                            selectedColor === color.name
                                                ? "ring-2 ring-offset-2 ring-blue-500 scale-105"
                                                : "hover:scale-105 border-gray-200 dark:border-gray-700",
                                            isLoading && "opacity-50 cursor-not-allowed"
                                        )}
                                        title={color.label}
                                    >
                                        {selectedColor === color.name && (
                                            <div className="absolute inset-0 flex items-center justify-center">
                                                <div className="w-3 h-3 bg-white rounded-full" />
                                            </div>
                                        )}
                                    </button>
                                ))}
                            </div>
                        )}

                        {autoColor && (
                            <div className={cn(
                                "p-3 rounded-lg border-2",
                                "bg-gradient-to-br",
                                type === 'personal' ? colorGradients.blue : colorGradients.purple,
                                "border-gray-200 dark:border-gray-700"
                            )}>
                                <div className="text-xs text-white/90 font-medium">
                                    Cor será gerada automaticamente: {type === 'personal' ? 'Azul' : 'Roxo'}
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Error message */}
                    {error && (
                        <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
                            <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
                        </div>
                    )}

                    <DialogFooter>
                        <Button
                            type="button"
                            variant="outline"
                            onClick={(e) => {
                                e.stopPropagation()
                                handleOpenChange(false)
                            }}
                            disabled={isLoading}
                        >
                            Cancelar
                        </Button>
                        <Button
                            type="submit"
                            onClick={(e) => e.stopPropagation()}
                            disabled={isLoading || !name.trim()}
                            className="gap-2"
                        >
                            {isLoading ? (
                                <>
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    Criando...
                                </>
                            ) : (
                                <>
                                    <Sparkles className="w-4 h-4" />
                                    Criar Planet
                                </>
                            )}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    )
}

